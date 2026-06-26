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

def get_road_x_global(y_m, offset_m=2048.0, S_playable=8192.0):
    """Vectorized calculation of the road center x-coordinate in meters."""
    y_local = y_m - offset_m
    y_local = np.clip(y_local, 0.0, S_playable)
    y_miles = y_local / 1024.0
    
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
    
    x_local = x_miles * 1024.0
    return x_local + offset_m

def main():
    t_start = time.time()
    print("=== FS25 12K New DEM Generator (Exactly 12288x12288 for 8K Maps) ===")
    
    # Configuration
    S_px = 12288  # Heightmap resolution in pixels (exactly 12288x12288)
    S_m = 12288    # Heightmap size in meters (12288x12288m)
    scale_m_to_px = 1.0  # 1 pixel = 1 meter
    offset_m = 2048.0   # Playable area (8192x8192) centered in the 12288 canvas
    
    seed = 20260608
    np.random.seed(seed)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dem_path = os.path.join(script_dir, "dem_new_12k.png")
    output_vis_path = os.path.join(script_dir, "dem_new_visual_12k.png")
    output_detail_vis_path = os.path.join(script_dir, "dem_new_visual_detail_12k.png")
    
    print(f"1. Generating coordinate grids for size {S_px}x{S_px} pixels ({S_m}x{S_m} meters)...")
    y_indices_px, x_indices_px = np.indices((S_px, S_px), dtype=np.float32)
    
    # Convert pixel indices to meter coordinates
    x_m = x_indices_px / scale_m_to_px
    y_m = y_indices_px / scale_m_to_px
    
    print("2. Generating geographic features (slope + rolling hills)...")
    # Global geographic slope: NW to SE (based on normalized coordinates)
    slope = (x_indices_px / (S_px - 1)) * 8000 + (y_indices_px / (S_px - 1)) * 26000 + 12000
    
    # Playable terrain noise (mostly flat rolling hills)
    noise_playable = (
        val_noise((S_px, S_px), 8, 3500, seed=seed) +
        val_noise((S_px, S_px), 16, 1200, seed=seed+1) +
        val_noise((S_px, S_px), 32, 400, seed=seed+2) +
        val_noise((S_px, S_px), 64, 100, seed=seed+3)
    )
    
    # Background mountain noise (high amplitude, surrounding the map)
    noise_mountains = (
        val_noise((S_px, S_px), 12, 22000, seed=seed+4) +
        val_noise((S_px, S_px), 24, 8000, seed=seed+5) +
        val_noise((S_px, S_px), 48, 2000, seed=seed+6)
    )
    
    # Compute background mountain weight (0 inside playable area x,y in [2048, 10240] meters, rises to 1.0 at 1024m away)
    dx_bg = np.maximum(0.0, np.maximum(2048.0 - x_m, x_m - 10240.0))
    dy_bg = np.maximum(0.0, np.maximum(2048.0 - y_m, y_m - 10240.0))
    dist_border_bg = np.sqrt(dx_bg*dx_bg + dy_bg*dy_bg)
    w_bg = np.minimum(1.0, dist_border_bg / 1024.0)
    
    # Natural base terrain (slope + hills + background mountains)
    natural_terrain = slope + noise_playable + w_bg * noise_mountains
    
    print("3. Implementing flat valley floor in the northern playable area...")
    # Flat zone boundary inside the playable area (in meters):
    # x_m in [2048, 10240] and y_m in [2048, 3584] (y_osm < 1536 + offset)
    rx0_m, rx1_m = 2048.0, 10240.0
    ry0_m, ry1_m = 2048.0, 3584.0
    W_TRANSITION = 500.0  # 500-meter transition ramp in all directions
    
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
    
    # Define flat weight: 1.0 inside the flat zone, transitions to 0.0 outside over 500m
    w_flat = np.zeros_like(dist_flat)
    w_flat[dist_flat == 0] = 1.0
    
    trans_mask = (dist_flat > 0) & (dist_flat <= W_TRANSITION)
    t = dist_flat[trans_mask] / W_TRANSITION
    w_flat[trans_mask] = 0.5 * (1.0 + np.cos(np.pi * t))
    
    # Blend flat height with natural terrain
    terrain = w_flat * H_north + (1.0 - w_flat) * natural_terrain
    
    print("   Smoothing entire terrain (macro-smoothing)...")
    # Smooth with adjusted sigma to scale with pixel resolution (6m = 9px)
    terrain = gaussian_filter(terrain, sigma=6 * scale_m_to_px)
    
    # Save a copy of terrain before adding hills to compute clean yard target heights
    terrain_before_hills = terrain.copy()
    
    # 4.1. Generate hills along the road (500m free corridor width, 80m max height, 1000m hill width)
    print("4.1. Generating hills along the road (500m free width, 1000m hill width, 80m height)...")
    road_x = get_road_x_global(y_m, offset_m)
    dist_to_road = np.abs(x_m - road_x)
    
    w_hill = 1000.0   # width of the hill band (extended to 1000m each side)
    d_start = 250.0   # clearance from road center (250m each side = 500m corridor)
    d_end = d_start + w_hill
    
    # Mask where hills are active
    hill_mask = (dist_to_road >= d_start) & (dist_to_road <= d_end)
    
    # Profile S(d) across the road
    S_d = np.zeros_like(dist_to_road)
    u_d = (dist_to_road[hill_mask] - d_start) / w_hill
    S_d[hill_mask] = np.sin(np.pi * u_d) ** 2
    
    # Variation P(y) along the road (chain of hills)
    val_y = (
        np.sin(y_m / 150.0) * 0.5 + 
        np.sin(y_m / 350.0) * 0.3 + 
        np.sin(y_m / 800.0) * 0.2
    )
    val_y_min = val_y.min()
    val_y_max = val_y.max()
    P_y = (val_y - val_y_min) / (val_y_max - val_y_min)
    P_y = P_y ** 2
    
    # Fade factor near northern/southern playable boundaries
    w_fade_y = np.zeros_like(y_m)
    mask_playable = (y_m >= 2048.0) & (y_m <= 10240.0)
    fade_len = 500.0
    y_play = y_m[mask_playable]
    w_play = np.ones_like(y_play)
    
    # North boundary fade (2048 to 2048 + fade_len)
    mask_north = y_play < (2048.0 + fade_len)
    w_play[mask_north] = (y_play[mask_north] - 2048.0) / fade_len
    
    # South boundary fade (10240 - fade_len to 10240)
    mask_south = y_play > (10240.0 - fade_len)
    w_play[mask_south] = (10240.0 - y_play[mask_south]) / fade_len
    
    w_fade_y[mask_playable] = w_play
    
    # Sinuous road y-range weight: 1.0 in sinuous part, fades to 0.0 at vertical parts
    y_local = np.clip(y_m - offset_m, 0.0, 8192.0)
    y_miles = y_local / 1024.0
    w_sinuous_y = np.ones_like(y_miles)
    
    # Top transition (fade out from y_miles=2.4 to y_miles=2.2)
    mask_top_fade = (y_miles >= 2.2) & (y_miles < 2.4)
    w_sinuous_y[mask_top_fade] = (y_miles[mask_top_fade] - 2.2) / 0.2
    w_sinuous_y[y_miles < 2.2] = 0.0
    
    # Bottom transition (fade out from y_miles=5.6 to y_miles=5.8)
    mask_bottom_fade = (y_miles > 5.6) & (y_miles <= 5.8)
    w_sinuous_y[mask_bottom_fade] = (5.8 - y_miles[mask_bottom_fade]) / 0.2
    w_sinuous_y[y_miles > 5.8] = 0.0
    
    # Max height is 80 meters (8000.0 raw units)
    H_max_raw = 80.0 * 100.0
    hill_heights = H_max_raw * S_d * P_y * w_fade_y * w_sinuous_y
    
    # Add hills to terrain
    terrain = terrain + hill_heights
    
    print("5. Flattening southern farmyards with extra-gentle transitions...")
    yards_to_flatten_m = [
        (4480.0 + offset_m, 1035.0 + offset_m, 4736.0 + offset_m, 1291.0 + offset_m, "Yard 1 (NE)"),
        (2406.0 + offset_m, 6850.0 + offset_m, 2714.0 + offset_m, 7157.0 + offset_m, "Yard 2 (SW)"),
        (4506.0 + offset_m, 6952.0 + offset_m, 4710.0 + offset_m, 7157.0 + offset_m, "Yard 3 (S)"),
        (6502.0 + offset_m, 6850.0 + offset_m, 6810.0 + offset_m, 7157.0 + offset_m, "Yard 4 (SE)"),
        (1035.0 + offset_m, 4506.0 + offset_m, 1240.0 + offset_m, 4710.0 + offset_m, "Yard 5 (W)"),
        (6645.0 + offset_m, 4352.0 + offset_m, 7157.0 + offset_m, 4864.0 + offset_m, "Yard 6 (E)"),
        (3846.0 + offset_m, 7380.0 + offset_m, 4346.0 + offset_m, 7880.0 + offset_m, "Yard 7 (Southern)"),
        (1664.0 + offset_m, 1024.0 + offset_m, 2048.0 + offset_m, 1536.0 + offset_m, "Town Farmyard")
    ]
    
    margin_m = 120.0  # 120m transition margin for southern yards
    
    for x0_m, y0_m, x1_m, y1_m, name in yards_to_flatten_m:
        x0_px = max(0, min(S_px-1, int(x0_m * scale_m_to_px)))
        x1_px = max(0, min(S_px-1, int(x1_m * scale_m_to_px)))
        y0_px = max(0, min(S_px-1, int(y0_m * scale_m_to_px)))
        y1_px = max(0, min(S_px-1, int(y1_m * scale_m_to_px)))
        
        # Calculate target height from the terrain before hills
        sub = terrain_before_hills[y0_px:y1_px+1, x0_px:x1_px+1]
        H_target = np.median(sub)
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
                    
        # Local Gaussian smoothing specifically to the transition ramp (sigma=10 * 1.5 = 15)
        local_terrain = terrain[by0_px:by1_px+1, bx0_px:bx1_px+1].copy()
        local_smoothed = gaussian_filter(local_terrain, sigma=10 * scale_m_to_px)
        
        for y_offset, y in enumerate(range(by0_px, by1_px + 1)):
            for x_offset, x in enumerate(range(bx0_px, bx1_px + 1)):
                if local_ramp[y_offset, x_offset]:
                    terrain[y, x] = local_smoothed[y_offset, x_offset]
                    
    # Clamp terrain to valid 16-bit range
    terrain = np.clip(terrain, 2000.0, 62000.0)
    
    print(f"6. Saving final DEM heightmap to '{output_dem_path}'...")
    img_out = Image.fromarray(terrain.astype(np.int32), mode="I")
    img_out.save(output_dem_path)
    print(f"   Saved heightmap successfully (Min={terrain.min():.1f}, Max={terrain.max():.1f}).")
    
    print("7. Generating visual maps...")
    vis_scale = 12  # Upscaled to match 1024x1024 visual dimension (12288 / 12 = 1024)
    terrain_vis = terrain[::vis_scale, ::vis_scale]
    
    ls = LightSource(azdeg=315, altdeg=45)
    hs = ls.shade(terrain_vis, cmap=plt.get_cmap('terrain'), vert_exag=0.12, blend_mode='overlay')
    
    # List of all areas (for highlighting, in meters)
    all_areas_m = [
        (1024.0 + offset_m, 1024.0 + offset_m, 1664.0 + offset_m, 1536.0 + offset_m, "Town"),
        (1664.0 + offset_m, 1024.0 + offset_m, 2048.0 + offset_m, 1536.0 + offset_m, "Town Farmyard"),
        (4480.0 + offset_m, 1035.0 + offset_m, 4736.0 + offset_m, 1291.0 + offset_m, "Yard 1 (NE)"),
        (2406.0 + offset_m, 6850.0 + offset_m, 2714.0 + offset_m, 7157.0 + offset_m, "Yard 2 (SW)"),
        (4506.0 + offset_m, 6952.0 + offset_m, 4710.0 + offset_m, 7157.0 + offset_m, "Yard 3 (S)"),
        (6502.0 + offset_m, 6850.0 + offset_m, 6810.0 + offset_m, 7157.0 + offset_m, "Yard 4 (SE)"),
        (1035.0 + offset_m, 4506.0 + offset_m, 1240.0 + offset_m, 4710.0 + offset_m, "Yard 5 (W)"),
        (6645.0 + offset_m, 4352.0 + offset_m, 7157.0 + offset_m, 4864.0 + offset_m, "Yard 6 (E)"),
        (3846.0 + offset_m, 7380.0 + offset_m, 4346.0 + offset_m, 7880.0 + offset_m, "Yard 7 (Southern)")
    ]
    
    # Define scale from meters to visualization coordinates: (scale_m_to_px / vis_scale) = 1.0 / 12 = 0.08333
    scale_m_to_vis = scale_m_to_px / vis_scale
    
    # --- Map 1: Full 12K Map View ---
    print("   Generating full map visualization...")
    fig, ax = plt.subplots(figsize=(12, 12), dpi=150)
    ax.imshow(hs)
    ax.axis('off')
    ax.set_title("Full 12K DEM Map (Exactly 12288x12288px - Valley Style)", fontsize=16, fontweight='bold', pad=15)
    
    playable_size_vis = 8192.0 * scale_m_to_vis
    playable_start_vis = 2048.0 * scale_m_to_vis
    rect_playable = plt.Rectangle((playable_start_vis, playable_start_vis), playable_size_vis, playable_size_vis, 
                                  fill=False, edgecolor='white', linewidth=2, linestyle='--', label='Playable Border (8km)')
    ax.add_patch(rect_playable)
    
    for x0_m, y0_m, x1_m, y1_m, name in all_areas_m:
        rect = plt.Rectangle((x0_m * scale_m_to_vis, y0_m * scale_m_to_vis), 
                             (x1_m - x0_m) * scale_m_to_vis, 
                             (y1_m - y0_m) * scale_m_to_vis, 
                             fill=False, edgecolor='#00FF00', linewidth=1.5, linestyle='-')
        ax.add_patch(rect)
        
    rect_flat_north = plt.Rectangle((rx0_m * scale_m_to_vis, ry0_m * scale_m_to_vis), 
                                     (rx1_m - rx0_m) * scale_m_to_vis, 
                                     (ry1_m - ry0_m) * scale_m_to_vis,
                                     fill=False, edgecolor='yellow', linewidth=2, linestyle=':', label='Flat North Area')
    ax.add_patch(rect_flat_north)
    
    plt.legend(handles=[rect_playable, rect_flat_north], loc='upper right', facecolor='black', labelcolor='white')
    plt.savefig(output_vis_path, bbox_inches='tight')
    plt.close()
    print(f"   Saved full visualization to '{output_vis_path}'.")
    
    # --- Map 2: Zoomed-in Playable Area View ---
    print("   Generating detailed playable area visualization...")
    p_start = int(2048.0 / vis_scale)  # 170
    p_end = int(10240.0 / vis_scale)   # 853
    hs_detail = hs[p_start:p_end, p_start:p_end]
    
    fig, ax = plt.subplots(figsize=(10, 10), dpi=150)
    ax.imshow(hs_detail)
    ax.axis('off')
    ax.set_title("Detailed Playable Area (12288x12288 canvas resolution)", fontsize=16, fontweight='bold', pad=15)
    
    for x0_m, y0_m, x1_m, y1_m, name in all_areas_m:
        x0_p = (x0_m * scale_m_to_vis) - p_start
        y0_p = (y0_m * scale_m_to_vis) - p_start
        w_p = (x1_m - x0_m) * scale_m_to_vis
        h_p = (y1_m - y0_m) * scale_m_to_vis
        
        rect = plt.Rectangle((x0_p, y0_p), w_p, h_p, fill=False, edgecolor='#00FF00', linewidth=2.5, linestyle='-')
        ax.add_patch(rect)
        ax.text(x0_p + 2, y0_p - 3, name, color='#00FF00', fontsize=8, fontweight='bold')
        
    flat_valley_y = (ry1_m * scale_m_to_vis) - p_start
    ax.axhline(y=flat_valley_y, color='yellow', linestyle=':', linewidth=2.5)
    ax.text(10, flat_valley_y - 8, "FLAT VALLEY FLOOR (North)", color='yellow', fontsize=10, fontweight='bold')
    ax.text(10, flat_valley_y + 15, "TRANSITION RAMP (500m)", color='yellow', fontsize=10, fontweight='bold')
    
    plt.savefig(output_detail_vis_path, bbox_inches='tight')
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
