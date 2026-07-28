import os
import time
import math
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

# For generating visual maps
import matplotlib
matplotlib.use('Agg') # Non-interactive backend
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource

def val_noise(shape, grid_size, weight, seed=20260608):
    """Generates smooth value noise by upscaling a small random grid using bicubic interpolation."""
    np.random.seed(seed)
    small = np.random.uniform(-1.0, 1.0, size=(grid_size, grid_size)).astype(np.float32)
    temp_img = Image.fromarray(small)
    temp_img = temp_img.resize((shape[1], shape[0]), Image.Resampling.BICUBIC)
    return np.array(temp_img) * weight

def get_road_x_global(y_m, offset_m=1024.0, S_playable=4096.0):
    """Vectorized calculation of the road center x-coordinate in meters."""
    y_local = y_m - offset_m
    y_local = np.clip(y_local, 0.0, S_playable)
    y_miles = y_local / 512.0

    x_miles = np.zeros_like(y_miles)

    mask1 = y_miles <= 2.2
    x_miles[mask1] = 7.0

    mask2 = (y_miles > 2.2) & (y_miles <= 3.8)
    u2 = (y_miles[mask2] - 2.2) / 1.6
    x_miles[mask2] = 4.0 + 3.0 * (1.0 + np.cos(np.pi * u2)) / 2.0

    mask3 = (y_miles > 3.8) & (y_miles <= 4.2)
    x_miles[mask3] = 4.0

    mask4 = (y_miles > 4.2) & (y_miles <= 5.8)
    u4 = (y_miles[mask4] - 4.2) / 1.6
    x_miles[mask4] = 1.0 + 3.0 * (1.0 + np.cos(np.pi * u4)) / 2.0

    mask5 = y_miles > 5.8
    x_miles[mask5] = 1.0

    x_local = x_miles * 512.0
    return x_local + offset_m

def main():
    t_start = time.time()
    print("=== FS25 6K New DEM Generator (Exactly 6144x6144 for 4K Maps) ===")

    # Configuration (x4 map: half the linear size of the x16 version)
    S_px = 6144   # Heightmap resolution in pixels (exactly 6144x6144)
    S_m = 6144    # Heightmap size in meters (6144x6144m)
    scale_m_to_px = 1.0  # 1 pixel = 1 meter
    offset_m = 1024.0   # Playable area (4096x4096) centered in the 6144 canvas

    seed = 20260608
    np.random.seed(seed)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dem_path = os.path.join(script_dir, "dem_new_6k.png")
    output_vis_path = os.path.join(script_dir, "dem_new_visual_6k.png")
    output_detail_vis_path = os.path.join(script_dir, "dem_new_visual_detail_6k.png")

    print(f"1. Generating coordinate grids for size {S_px}x{S_px} pixels ({S_m}x{S_m} meters)...")
    y_indices_px, x_indices_px = np.indices((S_px, S_px), dtype=np.float32)

    # Convert pixel indices to meter coordinates
    x_m = x_indices_px / scale_m_to_px
    y_m = y_indices_px / scale_m_to_px

    print("2. Generating geographic features (slope + rolling hills)...")
    # Global geographic slope: NW to SE (based on normalized coordinates).
    # Same normalized shape as the x16 map, so absolute elevations match at
    # corresponding relative positions (the forest threshold at 370m still works).
    slope = (x_indices_px / (S_px - 1)) * 8000 + (y_indices_px / (S_px - 1)) * 26000 + 12000

    # Playable terrain noise (mostly flat rolling hills)
    noise_playable = (
        val_noise((S_px, S_px), 8, 3500, seed=seed) +
        val_noise((S_px, S_px), 16, 1200, seed=seed+1) +
        val_noise((S_px, S_px), 32, 400, seed=seed+2) +
        val_noise((S_px, S_px), 64, 100, seed=seed+3)
    )

    # Background hills noise (low amplitude rolling plains/steppes to match Donetsk/Donets Ridge geography)
    noise_mountains = (
        val_noise((S_px, S_px), 8, 4500, seed=seed+4) +
        val_noise((S_px, S_px), 16, 2000, seed=seed+5) +
        val_noise((S_px, S_px), 32, 500, seed=seed+6)
    )

    # Compute background mountain weight (0 inside playable area x,y in [1024, 5120] meters, rises to 1.0 at 512m away)
    dx_bg = np.maximum(0.0, np.maximum(1024.0 - x_m, x_m - 5120.0))
    dy_bg = np.maximum(0.0, np.maximum(1024.0 - y_m, y_m - 5120.0))
    dist_border_bg = np.sqrt(dx_bg*dx_bg + dy_bg*dy_bg)
    w_bg = np.minimum(1.0, dist_border_bg / 512.0)

    # Natural base terrain (slope + hills + background mountains)
    natural_terrain = slope + noise_playable + w_bg * noise_mountains

    # Raise the South-East mountain zone by 50 meters (5000 raw units)
    # Center of the dome: SE corner of playable area (5120.0, 5120.0)
    # Radius: 1250 meters
    dx_mountain = x_m - 5120.0
    dy_mountain = y_m - 5120.0
    dist_mountain = np.sqrt(dx_mountain*dx_mountain + dy_mountain*dy_mountain)

    w_mountain = np.zeros_like(dist_mountain)
    mask_mountain = dist_mountain <= 1250.0
    t_mountain = dist_mountain[mask_mountain] / 1250.0
    w_mountain[mask_mountain] = 0.5 * (1.0 + np.cos(np.pi * t_mountain))

    natural_terrain += w_mountain * 5000.0

    print("3. Implementing flat valley floor in the northern playable area...")
    # Flat zone boundary inside the playable area (in meters):
    # x_m in [1024, 5120] and y_m in [1024, 1792] (y_osm < 768 + offset)
    rx0_m, rx1_m = 1024.0, 5120.0
    ry0_m, ry1_m = 1024.0, 1792.0
    W_TRANSITION = 250.0  # 250-meter transition ramp in all directions

    # Compute pixel indices for slicing natural_terrain
    rx0_px = int(rx0_m * scale_m_to_px)
    rx1_px = int(rx1_m * scale_m_to_px)
    ry1_px = int(ry1_m * scale_m_to_px)

    # Compute flat elevation height H_north dynamically as the median of the natural terrain
    # along the southern boundary of the flat zone inside the playable area
    H_north = np.median(natural_terrain[ry1_px, rx0_px:rx1_px+1])
    print(f"   Flat North Height (H_north): {H_north:.1f}")

    # Compute Euclidean distance in meters from every pixel to the flat rectangle
    dx_flat = np.maximum(0.0, np.maximum(rx0_m - x_m, x_m - rx1_m))
    dy_flat = np.maximum(0.0, np.maximum(ry0_m - y_m, y_m - ry1_m))
    dist_flat = np.sqrt(dx_flat*dx_flat + dy_flat*dy_flat)

    # Define flat weight: 1.0 inside the flat zone, transitions to 0.0 outside over 250m
    w_flat = np.zeros_like(dist_flat)
    w_flat[dist_flat == 0] = 1.0

    trans_mask = (dist_flat > 0) & (dist_flat <= W_TRANSITION)
    t = dist_flat[trans_mask] / W_TRANSITION
    w_flat[trans_mask] = 0.5 * (1.0 + np.cos(np.pi * t))

    # Blend flat height with natural terrain
    terrain = w_flat * H_north + (1.0 - w_flat) * natural_terrain

    print("   Smoothing entire terrain (macro-smoothing)...")
    # Smooth with adjusted sigma to scale with pixel resolution (3m = 3px)
    terrain = gaussian_filter(terrain, sigma=3 * scale_m_to_px)

    # Save a copy of terrain before farmyard flattening to compute clean yard target heights
    terrain_before_hills = terrain.copy()


    print("5. Flattening southern farmyards with extra-gentle transitions...")
    yards_to_flatten_m = [
        (12.5 + offset_m, 3833.5 + offset_m, 1012.5 + offset_m, 4083.5 + offset_m, "Yard 7 (Southern)"),
        (1027.5 + offset_m, 3833.5 + offset_m, 1322.7 + offset_m, 4083.5 + offset_m, "Field S_C1_1 (SW Hill)"),
        (3879.0 + offset_m, 512.0 + offset_m, 4071.0 + offset_m, 768.0 + offset_m, "Town Farmyard")
    ]

    margin_m = 60.0  # 60m transition margin for southern yards

    for x0_m, y0_m, x1_m, y1_m, name in yards_to_flatten_m:
        x0_px = max(0, min(S_px-1, int(x0_m * scale_m_to_px)))
        x1_px = max(0, min(S_px-1, int(x1_m * scale_m_to_px)))
        y0_px = max(0, min(S_px-1, int(y0_m * scale_m_to_px)))
        y1_px = max(0, min(S_px-1, int(y1_m * scale_m_to_px)))

        # Calculate target height from the terrain before hills. Capped below the
        # 370m forest threshold (37000 raw): Field S_C1_1 sits on the old SW hill, whose
        # median is slightly above it, and a yard flattened to forest elevation
        # would read as forest to the OSM generator instead of as open ground.
        sub = terrain_before_hills[y0_px:y1_px+1, x0_px:x1_px+1]
        H_target = min(np.median(sub), 36500.0)
        print(f"   Flattening {name} to target height = {H_target:.1f} (margin={margin_m}m)")

        bx0_px = max(0, int(x0_px - margin_m * scale_m_to_px - 5))
        bx1_px = min(S_px-1, int(x1_px + margin_m * scale_m_to_px + 5))
        by0_px = max(0, int(y0_px - margin_m * scale_m_to_px - 5))
        by1_px = min(S_px-1, int(y1_px + margin_m * scale_m_to_px + 5))

        terrain_ref = terrain.copy()

        ny = by1_px - by0_px + 1
        nx = bx1_px - bx0_px + 1
        local_ramp = np.zeros((ny, nx), dtype=bool)

        for y_offset, y in enumerate(range(by0_px, by1_px + 1)):
            for x_offset, x in enumerate(range(bx0_px, bx1_px + 1)):
                pt_x_m = x / scale_m_to_px
                pt_y_m = y / scale_m_to_px
                dx_pt_m = max(0.0, x0_m - pt_x_m, pt_x_m - x1_m)
                dy_pt_m = max(0.0, y0_m - pt_y_m, pt_y_m - y1_m)
                d_m = math.sqrt(dx_pt_m*dx_pt_m + dy_pt_m*dy_pt_m)

                if d_m == 0:
                    terrain[y, x] = H_target
                elif d_m <= margin_m:
                    w = 0.5 * (1.0 + math.cos(math.pi * d_m / margin_m))
                    terrain[y, x] = w * H_target + (1.0 - w) * terrain_ref[y, x]
                    local_ramp[y_offset, x_offset] = True

        # Local Gaussian smoothing specifically to the transition ramp
        local_terrain = terrain[by0_px:by1_px+1, bx0_px:bx1_px+1].copy()
        local_smoothed = gaussian_filter(local_terrain, sigma=5 * scale_m_to_px)

        for y_offset, y in enumerate(range(by0_px, by1_px + 1)):
            for x_offset, x in enumerate(range(bx0_px, bx1_px + 1)):
                if local_ramp[y_offset, x_offset]:
                    terrain[y, x] = local_smoothed[y_offset, x_offset]

    print("5.1. Creating 15m deep reservoir in Town Farmyard (180x180m)...")
    # Town Farmyard: x [3879..4071], y [512..768] (relative to offset_m)
    # Reservoir: x [3879..4059], y [588..768] (relative to offset_m)
    res_x0_m = 3879.0 + offset_m
    res_x1_m = 4059.0 + offset_m
    res_y0_m = 588.0 + offset_m
    res_y1_m = 768.0 + offset_m

    res_x0_px = int(res_x0_m * scale_m_to_px)
    res_x1_px = int(res_x1_m * scale_m_to_px)
    res_y0_px = int(res_y0_m * scale_m_to_px)
    res_y1_px = int(res_y1_m * scale_m_to_px)

    depth_m = 15.0
    depth_units = depth_m * 100.0  # 15m * 100 raw units/m = 1500 units
    bank_margin_m = 15.0  # 15m smooth sloped bank

    H_town_surface = np.median(terrain[res_y0_px:res_y1_px+1, res_x0_px:res_x1_px+1])
    print(f"   Town Farmyard Surface: {H_town_surface:.1f} -> Reservoir Floor: {H_town_surface - depth_units:.1f} (Depth: {depth_m}m)")

    terrain_before_res = terrain.copy()

    for y in range(res_y0_px, res_y1_px + 1):
        pt_y_m = y / scale_m_to_px
        dy_edge = min(pt_y_m - res_y0_m, res_y1_m - pt_y_m)
        for x in range(res_x0_px, res_x1_px + 1):
            pt_x_m = x / scale_m_to_px
            dx_edge = min(pt_x_m - res_x0_m, res_x1_m - pt_x_m)
            d_edge = min(dx_edge, dy_edge)

            if d_edge <= 0:
                w = 0.0
            elif d_edge < bank_margin_m:
                t = d_edge / bank_margin_m
                w = 0.5 * (1.0 - math.cos(math.pi * t))
            else:
                w = 1.0

            terrain[y, x] = terrain_before_res[y, x] - w * depth_units

    # Apply local Gaussian smoothing on the reservoir banks
    res_sub = terrain[res_y0_px-5:res_y1_px+6, res_x0_px-5:res_x1_px+6]
    terrain[res_y0_px-5:res_y1_px+6, res_x0_px-5:res_x1_px+6] = gaussian_filter(res_sub, sigma=2 * scale_m_to_px)
    print("5.2. Creating 5m deep canal into reservoir...")
    # Reservoir: x [3879..4059], y [588..768] (relative to offset_m)
    chan_x_west_m = res_x1_m  # Reservoir eastern wall
    chan_x_east_m = 4096.0 + offset_m + 100.0  # 100m into non-playable area
    chan_y_center_m = (res_y0_m + res_y1_m) / 2.0  # Midpoint of reservoir in Y

    chan_width_m = 5.0
    half_w_m = chan_width_m / 2.0  # 2.5m
    bank_w_m = 2.0  # 2m sloped bank

    cx0_px = int(chan_x_west_m * scale_m_to_px)
    cx1_px = int(chan_x_east_m * scale_m_to_px)
    cy0_px = int((chan_y_center_m - half_w_m - bank_w_m - 2.0) * scale_m_to_px)
    cy1_px = int((chan_y_center_m + half_w_m + bank_w_m + 2.0) * scale_m_to_px)

    terrain_before_chan = terrain.copy()

    for y in range(cy0_px, cy1_px + 1):
        pt_y_m = y / scale_m_to_px
        dy_center = abs(pt_y_m - chan_y_center_m)

        if dy_center > (half_w_m + bank_w_m):
            continue

        if dy_center <= half_w_m:
            w_profile = 1.0
        else:
            t_bank = (half_w_m + bank_w_m - dy_center) / bank_w_m
            w_profile = 0.5 * (1.0 - math.cos(math.pi * t_bank))

        for x in range(cx0_px, cx1_px + 1):
            depth_m = 5.0
            depth_units = depth_m * 100.0

            target_height = terrain_before_chan[y, x] - w_profile * depth_units
            terrain[y, x] = min(terrain[y, x], target_height)

    # Apply light Gaussian smoothing to channel edges
    chan_sub = terrain[cy0_px-3:cy1_px+4, cx0_px-5:cx1_px+6]
    terrain[cy0_px-3:cy1_px+4, cx0_px-5:cx1_px+6] = gaussian_filter(chan_sub, sigma=1 * scale_m_to_px)

    # Clamp terrain to valid 16-bit range
    terrain = np.clip(terrain, 2000.0, 62000.0)

    print(f"6. Saving final DEM heightmap to '{output_dem_path}'...")
    img_out = Image.fromarray(terrain.astype(np.int32), mode="I")
    img_out.save(output_dem_path)
    print(f"   Saved heightmap successfully (Min={terrain.min():.1f}, Max={terrain.max():.1f}).")

    print("7. Generating visual maps...")
    vis_scale = 6  # Upscaled to match 1024x1024 visual dimension (6144 / 6 = 1024)
    terrain_vis = terrain[::vis_scale, ::vis_scale]

    ls = LightSource(azdeg=315, altdeg=45)
    hs = ls.shade(terrain_vis, cmap=plt.get_cmap('terrain'), vert_exag=0.12, blend_mode='overlay')

    all_areas_m = [
        (3559.0 + offset_m, 512.0 + offset_m, 3879.0 + offset_m, 768.0 + offset_m, "Town"),
        (3879.0 + offset_m, 512.0 + offset_m, 4071.0 + offset_m, 768.0 + offset_m, "Town Farmyard"),
        (3879.0 + offset_m, 588.0 + offset_m, 4059.0 + offset_m, 768.0 + offset_m, "Town Reservoir (15m)"),
        (4059.0 + offset_m, 675.5 + offset_m, 4096.0 + offset_m + 100.0, 680.5 + offset_m, "East Canal (5m)"),
        (12.5 + offset_m, 3833.5 + offset_m, 1012.5 + offset_m, 4083.5 + offset_m, "Yard 7 (Southern)"),
        (1027.5 + offset_m, 3833.5 + offset_m, 1322.7 + offset_m, 4083.5 + offset_m, "Field S_C1_1 (SW Hill)")
    ]

    # Define scale from meters to visualization coordinates: (scale_m_to_px / vis_scale) = 1.0 / 6
    scale_m_to_vis = scale_m_to_px / vis_scale

    # --- Map 1: Full 6K Map View ---
    print("   Generating full map visualization...")
    fig, ax = plt.subplots(figsize=(12, 12), dpi=150)
    ax.imshow(hs, extent=[0, 6144, 6144, 0])

    # Grid and tick labels for 6.1km canvas
    ax.set_xlabel("X (East-West) [meters]", fontsize=12, fontweight='bold')
    ax.set_ylabel("Y (North-South) [meters]", fontsize=12, fontweight='bold')
    ax.set_xticks(np.arange(0, 6145, 512))
    ax.set_yticks(np.arange(0, 6145, 512))
    ax.grid(True, which='both', color='white', linestyle='--', linewidth=0.5, alpha=0.4)
    ax.tick_params(colors='white')
    # Dark theme styling
    fig.patch.set_facecolor('#111111')
    ax.set_facecolor('#111111')
    for spine in ax.spines.values():
        spine.set_color('white')
    ax.yaxis.label.set_color('white')
    ax.xaxis.label.set_color('white')
    ax.title.set_color('white')

    ax.set_title("Full 6K DEM Map (Exactly 6144x6144px - Valley Style)", fontsize=16, fontweight='bold', pad=15)

    rect_playable = plt.Rectangle((1024.0, 1024.0), 4096.0, 4096.0,
                                  fill=False, edgecolor='white', linewidth=2, linestyle='--', label='Playable Border (4km)')
    ax.add_patch(rect_playable)

    for x0_m, y0_m, x1_m, y1_m, name in all_areas_m:
        rect = plt.Rectangle((x0_m, y0_m), (x1_m - x0_m), (y1_m - y0_m),
                             fill=False, edgecolor='#00FF00', linewidth=1.5, linestyle='-')
        ax.add_patch(rect)

    rect_flat_north = plt.Rectangle((rx0_m, ry0_m), (rx1_m - rx0_m), (ry1_m - ry0_m),
                                     fill=False, edgecolor='yellow', linewidth=2, linestyle=':', label='Flat North Area')
    ax.add_patch(rect_flat_north)

    # Draw natural mountain shape contour lines for Bosque at 340m, 370m, 400m, 430m elevation
    x_range_all = np.arange(1024) * 6.0
    x_grid_vis, y_grid_vis = np.meshgrid(x_range_all, x_range_all)
    cnt = ax.contour(x_grid_vis, y_grid_vis, terrain_vis, levels=[34000.0, 37000.0, 40000.0, 43000.0], colors=['#00FF00'], linewidths=[1.0, 1.0, 1.5, 2.0], alpha=0.7)
    ax.clabel(cnt, inline=True, fmt=lambda x: f"{int(x/100)}m", fontsize=6, colors='#00FF00')

    plt.legend(handles=[rect_playable, rect_flat_north], loc='upper right', facecolor='black', labelcolor='white')
    plt.savefig(output_vis_path, bbox_inches='tight', facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    print(f"   Saved full visualization to '{output_vis_path}'.")

    # --- Map 2: Zoomed-in Playable Area View ---
    print("   Generating detailed playable area visualization...")
    p_start = int(1024.0 / vis_scale)  # 170
    p_end = int(5120.0 / vis_scale)    # 853
    hs_detail = hs[p_start:p_end, p_start:p_end]

    fig, ax = plt.subplots(figsize=(10, 10), dpi=150)
    ax.imshow(hs_detail, extent=[0, 4096, 4096, 0])

    # Grid and tick labels for 4km playable area relative coordinates
    ax.set_xlabel("X (East-West) [meters]", fontsize=12, fontweight='bold')
    ax.set_ylabel("Y (North-South) [meters]", fontsize=12, fontweight='bold')
    ax.set_xticks(np.arange(0, 4097, 512))
    ax.set_yticks(np.arange(0, 4097, 512))
    ax.grid(True, which='both', color='white', linestyle='--', linewidth=0.5, alpha=0.4)
    ax.tick_params(colors='white')
    # Dark theme styling
    fig.patch.set_facecolor('#111111')
    ax.set_facecolor('#111111')
    for spine in ax.spines.values():
        spine.set_color('white')
    ax.yaxis.label.set_color('white')
    ax.xaxis.label.set_color('white')
    ax.title.set_color('white')

    ax.set_title("Detailed Playable Area (4km x 4km Grid)", fontsize=16, fontweight='bold', pad=15)

    for x0_m, y0_m, x1_m, y1_m, name in all_areas_m:
        x0_p = x0_m - offset_m
        y0_p = y0_m - offset_m
        w_p = x1_m - x0_m
        h_p = y1_m - y0_m

        rect = plt.Rectangle((x0_p, y0_p), w_p, h_p, fill=False, edgecolor='#00FF00', linewidth=2.5, linestyle='-')
        ax.add_patch(rect)
        ax.text(x0_p + 8, y0_p - 13, name, color='#00FF00', fontsize=8, fontweight='bold')

    flat_valley_y = ry1_m - offset_m
    ax.axhline(y=flat_valley_y, color='yellow', linestyle=':', linewidth=2.5)
    ax.text(50, flat_valley_y - 40, "FLAT VALLEY FLOOR (North)", color='yellow', fontsize=10, fontweight='bold')
    ax.text(50, flat_valley_y + 75, "TRANSITION RAMP (250m)", color='yellow', fontsize=10, fontweight='bold')

    # Draw natural mountain shape contour lines for Bosque at 340m, 370m, 400m, 430m elevation
    x_range = np.arange(p_end - p_start) * 6.0
    x_grid_vis_playable, y_grid_vis_playable = np.meshgrid(x_range, x_range)
    terrain_vis_playable = terrain_vis[p_start:p_end, p_start:p_end]
    cnt = ax.contour(x_grid_vis_playable, y_grid_vis_playable, terrain_vis_playable,
                     levels=[34000.0, 37000.0, 40000.0, 43000.0], colors=['#00FF00'], linewidths=[1.5, 1.5, 2.0, 2.5], alpha=0.8)
    ax.clabel(cnt, inline=True, fmt=lambda x: f"{int(x/100)}m", fontsize=8, colors='#00FF00')
    ax.text(2500, 3400, "Bosque (Montaña SE)", color='#00FF00', fontsize=10, fontweight='bold')

    plt.savefig(output_detail_vis_path, bbox_inches='tight', facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    print(f"   Saved detailed visualization to '{output_detail_vis_path}'.")

    t_end = time.time()
    print(f"\n=== Script Completed Successfully in {t_end - t_start:.2f} seconds ===")
    print(f"Output files:")
    print(f" - New Heightmap: {output_dem_path}")
    print(f" - Full Map Visual: {output_vis_path}")
    print(f" - Detailed Visual: {output_detail_vis_path}")

if __name__ == "__main__":
    main()
