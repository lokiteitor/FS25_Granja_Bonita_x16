#!/usr/bin/env python3
import os
import math
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Map parameters
lat_center = 43.145692357357156
lon_center = -95.1450786604236
size_m = 8192.0 # Playable area size (8.192 km)

# Local coordinate to Lat/Lon conversion
def local_to_global(x, y):
    # x: 0 to 8192 (West to East)
    # y: 0 to 8192 (North to South)
    delta_y = 4096.0 - y
    delta_x = x - 4096.0
    lat = lat_center + (delta_y / 111111.0)
    lon = lon_center + (delta_x / (111111.0 * math.cos(math.radians(lat_center))))
    return lat, lon

def main():
    print("=== Generating OSM data for FS25 map ===")
    
    # 0. Load DEM once for elevation checks
    Image.MAX_IMAGE_PIXELS = None
    script_dir = os.path.dirname(os.path.abspath(__file__))
    dem_path = os.path.normpath(os.path.join(script_dir, "../dem_generator/dem_new_12k.png"))
    
    if not os.path.exists(dem_path):
        print(f"Error: DEM file not found at {dem_path}")
        return
        
    img = Image.open(dem_path)
    data = np.array(img, dtype=np.float32)
    playable = data[2048:10240, 2048:10240]
    
    # Forest checking helpers (Elevation >= 370m is forest)
    def is_in_forest(x, y, buffer_m=5.0):
        # The DEM decides on its own: wherever the terrain reaches 370m it is
        # forest, on either side of the Southern Link Road.
        x_min = max(0, int(x - buffer_m))
        x_max = min(8191, int(x + buffer_m))
        y_min = max(0, int(y - buffer_m))
        y_max = min(8191, int(y + buffer_m))
        
        sub = playable[y_min:y_max+1, x_min:x_max+1]
        if sub.size > 0 and np.any(sub >= 37000.0):
            return True
        return False

    def get_forest_limit_y(x, y_start, y_end, buffer_m=5.0):
        # Scan from y_start to y_end to find forest entry point, then step back by buffer_m
        y_limit = y_end
        for y in range(int(y_start), int(y_end) + 1):
            if is_in_forest(x, float(y), buffer_m=buffer_m):
                y_limit = float(y) - buffer_m
                break
        return y_limit

    # Pools
    nodes = {} # (x, y) -> node_id
    node_coords = {} # node_id -> (lat, lon)
    next_node_id = 1

    def get_node(x, y):
        nonlocal next_node_id
        key = (round(x, 3), round(y, 3))
        if key not in nodes:
            lat, lon = local_to_global(x, y)
            nodes[key] = next_node_id
            node_coords[next_node_id] = (lat, lon)
            next_node_id += 1
        return nodes[key]

    ways = [] # list of dicts: {'id': id, 'node_refs': [...], 'tags': {...}}
    next_way_id = 1

    def add_way(coords, tags):
        nonlocal next_way_id
        node_refs = [get_node(x, y) for x, y in coords]
        ways.append({
            'id': next_way_id,
            'node_refs': node_refs,
            'coords': [(float(x), float(y)) for x, y in coords], # local metres, used by the infill pass
            'tags': tags
        })
        next_way_id += 1

    # 1. Bounding box calculations
    minlat, minlon = local_to_global(0, 8192) # South-West
    maxlat, maxlon = local_to_global(8192, 0) # North-East

    # 2. Yard 7 (Southern)
    # X: 25 to 525, Y: 7667 to 8167
    yard7_coords = [
        (25.0, 7667.0),
        (525.0, 7667.0),
        (525.0, 8167.0),
        (25.0, 8167.0),
        (25.0, 7667.0) # Closed
    ]
    add_way(yard7_coords, {'landuse': 'farmyard', 'name': 'Yard 7'})

    # 3. Yard Town (Town Farmyard)
    # X: 7758 to 8142, Y: 1024 to 1536
    yard_town_coords = [
        (7758.0, 1024.0),
        (8142.0, 1024.0),
        (8142.0, 1536.0),
        (7758.0, 1536.0),
        (7758.0, 1024.0) # Closed
    ]
    add_way(yard_town_coords, {'landuse': 'farmyard', 'name': 'Town Farmyard'})

    # 4. Town Reservoir (Embalse)
    # X: 7758 to 8118, Y: 1176 to 1536
    reservoir_coords = [
        (7758.0, 1176.0),
        (8118.0, 1176.0),
        (8118.0, 1536.0),
        (7758.0, 1536.0),
        (7758.0, 1176.0) # Closed
    ]
    add_way(reservoir_coords, {'natural': 'water', 'name': 'Town Reservoir'})

    # 5. East Canal (Canal)
    # X: 8118 to 8392, Y: 1351 to 1361
    canal_coords = [
        (8118.0, 1351.0),
        (8392.0, 1351.0),
        (8392.0, 1361.0),
        (8118.0, 1361.0),
        (8118.0, 1351.0) # Closed
    ]
    add_way(canal_coords, {'natural': 'water', 'name': 'East Canal'})

    # 6. Town
    # X: 7118 to 7758, Y: 1024 to 1536
    town_coords = [
        (7118.0, 1024.0),
        (7758.0, 1024.0),
        (7758.0, 1536.0),
        (7118.0, 1536.0),
        (7118.0, 1024.0) # Closed
    ]
    add_way(town_coords, {'landuse': 'farmyard', 'name': 'Town'})

    # 7. Primary Road (East-West)
    # Passing 15m north of Town (Y: 1024 - 15 = 1009)
    # Spans from X: 0 to X: 8192.
    xs_sec = [7118.0, 7278.0, 7438.0, 7598.0, 7758.0]
    xs_ter_v = [800.0, 1600.0, 2400.0, 3200.0, 4000.0, 4800.0, 5600.0, 6400.0]
    xs_primary_all = sorted([7103.0] + xs_ter_v + xs_sec)
    primary_coords = [(0.0, 1009.0)] + [(x, 1009.0) for x in xs_primary_all] + [(8192.0, 1009.0)]
    add_way(primary_coords, {'highway': 'primary', 'name': 'Primary Road'})

    # 7b. New Southern-to-Western Primary Road
    def bezier_curve(p0, p1, p2, num_pts=10):
        pts = []
        for i in range(num_pts):
            t = i / (num_pts - 1)
            x = (1-t)**2 * p0[0] + 2*(1-t)*t * p1[0] + t**2 * p2[0]
            y = (1-t)**2 * p0[1] + 2*(1-t)*t * p1[1] + t**2 * p2[1]
            pts.append((x, y))
        return pts

    new_primary_coords_base = []
    # Segment 1: West edge to start of Curve 1
    new_primary_coords_base.append((0.0, 7650.0))
    new_primary_coords_base.append((5068.0, 7650.0))
    
    # Curve 1
    c1_pts = bezier_curve((5068.0, 7650.0), (5368.0, 7650.0), (5580.13, 7437.87))
    new_primary_coords_base.extend(c1_pts[1:-1])
    
    # Segment 2: end of Curve 1 to start of Curve 2
    new_primary_coords_base.append((5580.13, 7437.87))
    new_primary_coords_base.append((6890.87, 6127.13))
    
    # Curve 2
    c2_pts = bezier_curve((6890.87, 6127.13), (7103.0, 5915.0), (7103.0, 5615.0))
    new_primary_coords_base.extend(c2_pts[1:-1])
    
    # Segment 3: end of Curve 2 to connection with northern primary road
    new_primary_coords_base.append((7103.0, 5615.0))
    new_primary_coords_base.append((7103.0, 1536.0))
    new_primary_coords_base.append((7103.0, 1280.0))
    new_primary_coords_base.append((7103.0, 1024.0))
    new_primary_coords_base.append((7103.0, 1009.0))

    # Set up interpolation variables for the road shape
    road_pts_filtered = [pt for pt in new_primary_coords_base if pt[0] < 7103.0]
    road_pts_filtered.sort(key=lambda pt: pt[0])
    road_xs_interp = [pt[0] for pt in road_pts_filtered] + [7103.0]
    road_ys_interp = [pt[1] for pt in road_pts_filtered] + [5615.0]

    def get_road_y(x):
        if x >= 7103.0:
            return 5615.0
        return np.interp(x, road_xs_interp, road_ys_interp)

    road_pts_sorted_by_y = sorted(new_primary_coords_base, key=lambda pt: pt[1])
    road_xs_y = [pt[0] for pt in road_pts_sorted_by_y]
    road_ys_y = [pt[1] for pt in road_pts_sorted_by_y]

    # Collect and insert road-grid intersection nodes
    ys_ter_h = [1809.0, 2609.0, 3409.0, 4209.0, 5009.0, 5809.0, 6609.0, 7409.0]
    intersections = []
    for x in xs_ter_v:
        y_int = get_road_y(x)
        intersections.append((x, y_int))
    for y in ys_ter_h:
        x_int = np.interp(y, road_ys_y, road_xs_y)
        intersections.append((x_int, y))

    # Add intersections to primary road way, sort by X-Y (strictly monotonic along road path)
    all_road_nodes = list(set(new_primary_coords_base + intersections))
    all_road_nodes.sort(key=lambda pt: pt[0] - pt[1])
    add_way(all_road_nodes, {'highway': 'primary', 'name': 'Southern Link Road'})

    # 8. Railway
    # Passing 15m north of Primary Road (Y: 1009 - 15 = 994)
    # Parallel to Primary Road
    rail_coords = [(0.0, 994.0), (8192.0, 994.0)]
    add_way(rail_coords, {'railway': 'rail', 'name': 'Railway'})

    # 9. Secondary Roads (Grid in Town)
    ys_sec_v = [1009.0, 1024.0, 1280.0, 1536.0]
    for x in xs_sec:
        v_coords = [(x, y) for y in ys_sec_v]
        add_way(v_coords, {'highway': 'secondary'})

    xs_sec_h = [7103.0] + xs_sec
    ys_sec_h = [1024.0, 1280.0, 1536.0]
    for y in ys_sec_h:
        h_coords = [(x, y) for x in xs_sec_h]
        add_way(h_coords, {'highway': 'secondary'})

    # 9b. Tertiary Roads (PLSS Dirt Grid) - Stopping before entering forests
    # Vertical tertiary roads
    for x in xs_ter_v:
        y_int = get_road_y(x)
        v_pts = [(x, 1009.0)]
        for y in ys_ter_h:
            if y < y_int - 0.1:
                if is_in_forest(x, y, buffer_m=5.0):
                    break
                v_pts.append((x, y))
        
        if not is_in_forest(x, y_int, buffer_m=5.0):
            v_pts.append((x, y_int))
        else:
            y_forest_limit = get_forest_limit_y(x, 1009.0, y_int, buffer_m=5.0)
            if y_forest_limit > v_pts[-1][1] + 1.0:
                v_pts.append((x, y_forest_limit))
                
        v_pts.sort(key=lambda pt: pt[1])
        add_way(v_pts, {'highway': 'tertiary'})

    # Horizontal tertiary roads
    for y in ys_ter_h:
        x_int = np.interp(y, road_ys_y, road_xs_y)
        h_pts = [(0.0, y)]
        for x in xs_ter_v:
            if x < x_int - 0.1:
                if is_in_forest(x, y, buffer_m=5.0):
                    break
                h_pts.append((x, y))
                
        if not is_in_forest(x_int, y, buffer_m=5.0):
            h_pts.append((x_int, y))
        else:
            x_forest_limit = x_int
            for x_scan in range(0, int(x_int) + 1):
                if is_in_forest(float(x_scan), y, buffer_m=5.0):
                    x_forest_limit = float(x_scan) - 5.0
                    break
            if x_forest_limit > h_pts[-1][0] + 1.0:
                h_pts.append((x_forest_limit, y))
                
        h_pts.sort(key=lambda pt: pt[0])
        add_way(h_pts, {'highway': 'tertiary'})

    # 9c. PLSS Farmlands & Random Forests
    xs_grid_lines = [0.0] + xs_ter_v + [7103.0]
    ys_grid_lines = [1009.0] + ys_ter_h + [7650.0]
    
    # 1. Select 10 random cells to place forests
    import random
    candidates = []
    clear_cells = set()
    for i in range(len(xs_grid_lines) - 1):
        x_a = xs_grid_lines[i]
        x_b = xs_grid_lines[i+1]
        for j in range(len(ys_grid_lines) - 1):
            y_a = ys_grid_lines[j]
            y_b = ys_grid_lines[j+1]
            
            # Forest box size (10 hectares = 316.227m x 316.227m)
            forest_w = 316.227
            x_f_start = x_a + 5.0
            x_f_end = x_f_start + forest_w
            y_f_start = y_a + 5.0
            y_f_end = y_f_start + forest_w
            
            if x_f_end > 7098.0:
                continue
                
            # Check road clearance
            road_clear = True
            for x in np.linspace(x_f_start, x_f_end, 5):
                if y_f_end > get_road_y(x) - 5.0:
                    road_clear = False
                    break
            if not road_clear:
                continue
                
            candidates.append((i, j))

            # Check forest clearance (don't overlay on the existing mountain/hill forests).
            # Recorded rather than filtered here: dropping cells before the shuffle would
            # reshuffle every draw and move all ten forests, so the check is applied to the
            # shuffled order instead and only the offending cells are skipped.
            corners = [
                (x_f_start, y_f_start),
                (x_f_end, y_f_start),
                (x_f_end, y_f_end),
                (x_f_start, y_f_end)
            ]
            if not any(is_in_forest(cx, cy, buffer_m=5.0) for cx, cy in corners):
                clear_cells.add((i, j))

    print(f"   Found {len(candidates)} candidate cells for 10-hectare random forests "
          f"({len(clear_cells)} clear of the mountain forests).")
    # Deterministic seeded selection
    rng = random.Random(42)
    candidates.sort()
    rng.shuffle(candidates)
    selected_cells = set([c for c in candidates if c in clear_cells][:10])
    
    field_idx = 1
    forest_idx = 1
    cell_forest_idx = 1

    # PLSS cells (x-index, y-index into xs_grid_lines / ys_grid_lines) that are
    # forested instead of farmed. (2, 8) is the strip x[1600-2400] y[7409-7650],
    # wedged between the last tertiary road and the Southern Link Road, facing the
    # south-western forest across the road.
    wooded_cells = {(2, 8)}

    # PLSS cells kept as yard rather than farmland. (5, 8) is x[4000-4800] y[7409-7650],
    # the 18.2 ha strip against the Southern Link Road that used to be Field 61.
    yard_cells = {(5, 8)}

    print("   Generating PLSS farmlands (fields) and 10 random forests...")
    for i in range(len(xs_grid_lines) - 1):
        x_a = xs_grid_lines[i]
        x_b = xs_grid_lines[i+1]
        for j in range(len(ys_grid_lines) - 1):
            y_a = ys_grid_lines[j]
            y_b = ys_grid_lines[j+1]
            
            if (i, j) in selected_cells:
                # Add 10-hectare forest at the top-left of the cell
                forest_w = 316.227
                x_f_start = x_a + 5.0
                x_f_end = x_f_start + forest_w
                y_f_start = y_a + 5.0
                y_f_end = y_f_start + forest_w
                
                forest_coords = [
                    (x_f_start, y_f_start),
                    (x_f_end, y_f_start),
                    (x_f_end, y_f_end),
                    (x_f_start, y_f_end),
                    (x_f_start, y_f_start)
                ]
                add_way(forest_coords, {
                    'natural': 'wood',
                    'landuse': 'farmyard',
                    'leaf_type': 'broadleave',
                    'name': f'Random Forest {forest_idx}'
                })
                forest_idx += 1
                
                # Split remaining cell area into two fields: Right and Bottom
                # 1. Right Field
                xs_sample = np.linspace(x_f_end + 10.0, x_b - 5.0, 5)
                poly_top = []
                poly_bottom = []
                valid = True
                for x in xs_sample:
                    y_t = y_a + 5.0
                    y_b_limit = min(y_f_end, get_road_y(x) - 5.0)
                    y_b_limit = get_forest_limit_y(x, y_t, y_b_limit, buffer_m=5.0)
                    if x < 5.0 or x > 7098.0:
                        valid = False
                        break
                    if y_t + 15.0 > y_b_limit:
                        valid = False
                        break
                    poly_top.append((x, y_t))
                    poly_bottom.append((x, y_b_limit))
                if valid:
                    coords = poly_top + list(reversed(poly_bottom)) + [poly_top[0]]
                    add_way(coords, {'landuse': 'farmland', 'name': f'Field {field_idx}'})
                    field_idx += 1
                    
                # 2. Bottom Field
                xs_sample = np.linspace(x_a + 5.0, x_b - 5.0, 5)
                poly_top = []
                poly_bottom = []
                valid = True
                for x in xs_sample:
                    y_t = y_f_end + 10.0
                    y_b_limit = min(y_b - 5.0, get_road_y(x) - 5.0)
                    y_b_limit = get_forest_limit_y(x, y_t, y_b_limit, buffer_m=5.0)
                    if x < 5.0 or x > 7098.0:
                        valid = False
                        break
                    if y_t + 15.0 > y_b_limit:
                        valid = False
                        break
                    poly_top.append((x, y_t))
                    poly_bottom.append((x, y_b_limit))
                if valid:
                    coords = poly_top + list(reversed(poly_bottom)) + [poly_top[0]]
                    add_way(coords, {'landuse': 'farmland', 'name': f'Field {field_idx}'})
                    field_idx += 1
            else:
                # Normal full field in cell
                xs_sample = np.linspace(x_a + 5.0, x_b - 5.0, 5)
                poly_top = []
                poly_bottom = []
                valid = True
                for x in xs_sample:
                    y_t = y_a + 5.0
                    y_b_limit = min(y_b - 5.0, get_road_y(x) - 5.0)
                    y_b_limit = get_forest_limit_y(x, y_t, y_b_limit, buffer_m=5.0)
                    if x < 5.0 or x > 7098.0:
                        valid = False
                        break
                    if y_t < 1014.0:
                        y_t = 1014.0
                    if is_in_forest(x, y_t, buffer_m=5.0):
                        valid = False
                        break
                    if y_t + 15.0 > y_b_limit:
                        valid = False
                        break
                    poly_top.append((x, y_t))
                    poly_bottom.append((x, y_b_limit))
                if valid:
                    coords = poly_top + list(reversed(poly_bottom)) + [poly_top[0]]
                    if (i, j) in wooded_cells:
                        # No field here: the cell is given over to the forest that
                        # already borders it on the far side of the Southern Link Road.
                        add_way(coords, {
                            'natural': 'wood',
                            'landuse': 'farmyard',
                            'leaf_type': 'needleleave',
                            'name': f'Cell Forest {cell_forest_idx}'
                        })
                        cell_forest_idx += 1
                    else:
                        # Yard cells still consume a field number, so converting one
                        # does not renumber every field that comes after it.
                        if (i, j) in yard_cells:
                            add_way(coords, {'landuse': 'farmyard', 'name': f'Yard {field_idx}'})
                        else:
                            add_way(coords, {'landuse': 'farmland', 'name': f'Field {field_idx}'})
                        field_idx += 1

    print(f"   Added {field_idx - 1} PLSS fields, {forest_idx - 1} random forests "
          f"and {cell_forest_idx - 1} wooded cells.")

    # 9d. Northern Farmlands & Tertiary Roads (Horizontal layout, 15m borders)
    def pack_strip_horiz(y_start, y_end, seed):
        import random
        rng = random.Random(seed)
        fields = []
        roads = []
        
        x_curr = 15.0
        field_h = y_end - y_start
        
        # We select sizes from [5, 10, 20]
        # To have a good mix, we weight them: 5 ha (weight 2), 10 ha (weight 2), 20 ha (weight 1)
        choices = [5, 5, 10, 10, 20]
        
        while True:
            size = rng.choice(choices)
            w = (size * 10000.0) / field_h
            
            # Check if this field fits (needs at least w + 10m before 8177.0)
            if x_curr + w + 10.0 > 8177.0:
                # Last field: adjust to fill remaining space up to 8177.0
                w_rem = 8177.0 - x_curr
                if w_rem >= 50.0:
                    actual_size = (w_rem * field_h) / 10000.0
                    fields.append((x_curr, x_curr + w_rem, actual_size))
                break
                
            fields.append((x_curr, x_curr + w, size))
            # Vertical road in the gap (centered)
            roads.append(x_curr + w + 5.0)
            x_curr += w + 10.0
            
        return fields, roads

    print("   Generating Northern Farmlands (Horizontal standard, 15m borders)...")

    # Northern strip parcels (strip number, field number) kept as yard, not farmland.
    north_yards = {(5, 1)}
    
    # Define 5 strips of height 180m
    strips = [
        (15.0, 195.0),
        (205.0, 385.0),
        (395.0, 575.0),
        (585.0, 765.0),
        (775.0, 955.0)
    ]
    
    # Add horizontal boundary roads & horizontal roads in the gaps
    # Boundary North
    add_way([(15.0, 15.0), (8177.0, 15.0)], {'highway': 'tertiary'})
    # Gaps horizontal roads
    add_way([(0.0, 200.0), (8192.0, 200.0)], {'highway': 'tertiary'})
    add_way([(0.0, 390.0), (8192.0, 390.0)], {'highway': 'tertiary'})
    add_way([(0.0, 580.0), (8192.0, 580.0)], {'highway': 'tertiary'})
    add_way([(0.0, 770.0), (8192.0, 770.0)], {'highway': 'tertiary'})
    
    # Boundary West (15m offset)
    add_way([(15.0, 15.0), (15.0, 1009.0)], {'highway': 'tertiary'})
    # Boundary East (15m offset, which is 8177.0)
    add_way([(8177.0, 15.0), (8177.0, 1009.0)], {'highway': 'tertiary'})

    # Generate fields & vertical roads for each strip
    for s_idx, (y_s, y_e) in enumerate(strips):
        fields, roads = pack_strip_horiz(y_s, y_e, seed=(303 + s_idx))
        
        # Add fields
        for f_idx, (x_start, x_end, size) in enumerate(fields):
            coords = [
                (x_start, y_s),
                (x_end, y_s),
                (x_end, y_e),
                (x_start, y_e),
                (x_start, y_s)
            ]
            label = f'N{s_idx+1}_{f_idx+1}'
            if (s_idx + 1, f_idx + 1) in north_yards:
                add_way(coords, {'landuse': 'farmyard', 'name': f'Yard {label}'})
            else:
                add_way(coords, {'landuse': 'farmland', 'name': f'Field {label} ({size:.1f} ha)'})
            
        # Add vertical roads in gaps connecting adjacent horizontal roads
        for rx in roads:
            if s_idx == 0:
                # North border to Gap 1
                add_way([(rx, 15.0), (rx, 200.0)], {'highway': 'tertiary'})
            elif s_idx == 1:
                # Gap 1 to Gap 2
                add_way([(rx, 200.0), (rx, 390.0)], {'highway': 'tertiary'})
            elif s_idx == 2:
                # Gap 2 to Gap 3
                add_way([(rx, 390.0), (rx, 580.0)], {'highway': 'tertiary'})
            elif s_idx == 3:
                # Gap 3 to Gap 4
                add_way([(rx, 580.0), (rx, 770.0)], {'highway': 'tertiary'})
            elif s_idx == 4:
                # Gap 4 to primary road (crosses railway at 994)
                add_way([(rx, 770.0), (rx, 994.0), (rx, 1009.0)], {'highway': 'tertiary'})

    # 9e. Eastern Farmlands & Tertiary Roads (Vertical layout, 15m borders)
    print("   Generating Eastern Farmlands (Vertical 30 and 45 hectares) and tertiary roads...")
    
    col_w = 346.3
    col_xs = [
        (7118.0, 7464.3),
        (7474.3, 7820.6),
        (7830.6, 8177.0)
    ]
    vertical_gaps = [7469.3, 7825.6]
    
    # Pack fields for each column, keeping track of last horizontal road Y
    import random
    rng = random.Random(404)
    col_last_ys = [1536.0, 1536.0, 1536.0]
    
    for c_idx, (x_s, x_e) in enumerate(col_xs):
        y_curr = 1551.0
        choices = [30, 30, 45]
        f_idx = 1
        
        # Determine column road boundaries
        x_road_start = 7103.0 if c_idx == 0 else vertical_gaps[c_idx - 1]
        x_road_end = 8177.0 if c_idx == 2 else vertical_gaps[c_idx]
        
        while True:
            # Get forest limit Y for this column width
            col_y_limit = min(
                min(get_road_y(x) - 15.0, get_forest_limit_y(x, y_curr, 8192.0, buffer_m=15.0))
                for x in np.linspace(x_s, x_e, 5)
            )
            
            size = rng.choice(choices)
            h = (size * 10000.0) / col_w
            
            if y_curr + h + 10.0 > col_y_limit:
                # Discard the last field to avoid broken shapes bordering the forest
                break
                
            # Place field
            coords = [
                (x_s, y_curr),
                (x_e, y_curr),
                (x_e, y_curr + h),
                (x_s, y_curr + h),
                (x_s, y_curr)
            ]
            add_way(coords, {'landuse': 'farmland', 'name': f'Field E{c_idx+1}_{f_idx} ({size:.1f} ha)'})
            
            # Add horizontal road in the gap (restricted strictly to the column width)
            y_road = y_curr + h + 5.0
            add_way([(x_road_start, y_road), (x_road_end, y_road)], {'highway': 'tertiary'})
            
            col_last_ys[c_idx] = y_road
            
            y_curr += h + 10.0
            f_idx += 1

    # Add vertical roads in the column gaps, trimmed to the last horizontal road of the adjacent columns
    for g_idx, rx in enumerate(vertical_gaps):
        # Gap road goes down to the maximum of the last road in its left and right columns
        y_lim = max(col_last_ys[g_idx], col_last_ys[g_idx + 1])
        add_way([(rx, 1536.0), (rx, y_lim)], {'highway': 'tertiary'})
        
    # Boundary East road extension down to the last road in column 2
    y_lim_east = col_last_ys[2]
    add_way([(8177.0, 1536.0), (8177.0, y_lim_east)], {'highway': 'tertiary'})

    # 9f. Southern Farmlands & Tertiary Roads (Horizontal layout, 15m borders)
    print("   Generating Southern Farmlands (Horizontal 10 hectares) and tertiary roads...")
    
    def pack_south_pocket(x_start, x_end, seed, p_name):
        y_s1, y_e1 = 7665.0, 7916.0
        y_s2, y_e2 = 7926.0, 8177.0
        
        field_h = 251.0
        w_10ha = 398.4
        
        # Add horizontal roads at Y = 7921.0 and Y = 8177.0
        add_way([(x_start, 7921.0), (x_end, 7921.0)], {'highway': 'tertiary'})
        add_way([(x_start, 8177.0), (x_end, 8177.0)], {'highway': 'tertiary'})
        
        # Add boundary vertical roads
        add_way([(x_start, 7650.0), (x_start, 8177.0)], {'highway': 'tertiary'})
        add_way([(x_end, 7650.0), (x_end, 8177.0)], {'highway': 'tertiary'})
        
        # Pack fields
        import random
        rng = random.Random(seed)
        
        for strip_idx, (y_s, y_e) in enumerate([(y_s1, y_e1), (y_s2, y_e2)]):
            x_curr = x_start
            f_idx = 1
            roads = []
            
            while True:
                if x_curr + w_10ha + 10.0 > x_end:
                    w_rem = x_end - x_curr
                    if w_rem >= 100.0:
                        actual_size = (w_rem * field_h) / 10000.0
                        coords = [
                            (x_curr, y_s),
                            (x_curr + w_rem, y_s),
                            (x_curr + w_rem, y_e),
                            (x_curr, y_e),
                            (x_curr, y_s)
                        ]
                        add_way(coords, {'landuse': 'farmland', 'name': f'Field S_{p_name}{strip_idx+1}_{f_idx} ({actual_size:.1f} ha)'})
                    break
                    
                coords = [
                    (x_curr, y_s),
                    (x_curr + w_10ha, y_s),
                    (x_curr + w_10ha, y_e),
                    (x_curr, y_e),
                    (x_curr, y_s)
                ]
                add_way(coords, {'landuse': 'farmland', 'name': f'Field S_{p_name}{strip_idx+1}_{f_idx} (10.0 ha)'})
                
                roads.append(x_curr + w_10ha + 5.0)
                x_curr += w_10ha + 10.0
                f_idx += 1
                
            if strip_idx == 0:
                for rx in roads:
                    add_way([(rx, 7650.0), (rx, 8177.0)], {'highway': 'tertiary'})

    # Pocket A: between Yard 7 and bottom-left forest
    pack_south_pocket(540.0, 1981.8, seed=505, p_name="A")
    # Pocket B: between bottom-left forest and Southern Link Road curve 1
    pack_south_pocket(2675.4, 5053.0, seed=606, p_name="B")

    # 10. Forest polygons (elevations >= 370m)
    def get_border(pt):
        x, y = pt
        if math.isclose(x, 0.0, abs_tol=1e-3): return 'W'
        if math.isclose(x, 8192.0, abs_tol=1e-3): return 'E'
        if math.isclose(y, 0.0, abs_tol=1e-3): return 'N'
        if math.isclose(y, 8192.0, abs_tol=1e-3): return 'S'
        return None

    def close_segment(seg):
        start = seg[0]
        end = seg[-1]
        
        if np.allclose(start, end, atol=1e-3):
            return [tuple(pt) for pt in seg]
            
        border_start = get_border(start)
        border_end = get_border(end)
        
        path = [tuple(pt) for pt in seg]
        
        if border_start and border_end:
            if border_start == border_end:
                path.append(tuple(start))
            else:
                corners = {
                    ('E', 'S'): (8192.0, 8192.0),
                    ('S', 'E'): (8192.0, 8192.0),
                    ('W', 'S'): (0.0, 8192.0),
                    ('S', 'W'): (0.0, 8192.0),
                    ('E', 'N'): (8192.0, 0.0),
                    ('N', 'E'): (8192.0, 0.0),
                    ('W', 'N'): (0.0, 0.0),
                    ('N', 'W'): (0.0, 0.0),
                }
                pair = (border_end, border_start)
                if pair in corners:
                    path.append(corners[pair])
                path.append(tuple(start))
        else:
            path.append(tuple(start))
            
        return path

    def get_forest_polygons():
        grid_size = 257
        idx = np.linspace(0, 8191, grid_size, dtype=int)
        playable_sub = playable[idx, :][:, idx]
        
        x_grid = np.linspace(0, 8192, grid_size)
        y_grid = np.linspace(0, 8192, grid_size)
        X, Y = np.meshgrid(x_grid, y_grid)
        
        fig, ax = plt.subplots()
        cs = ax.contour(X, Y, playable_sub, levels=[37000.0])
        plt.close(fig)
        
        segs = cs.allsegs[0]
        polygons = []
        for seg in segs:
            closed_poly = close_segment(seg)
            polygons.append(closed_poly)
            
        return polygons

    print("   Extracting and generating forest areas from DEM (elevation >= 370m)...")
    forest_polys = get_forest_polygons()
    for i, poly in enumerate(forest_polys):
        # No clipping against the Southern Link Road: the 370m contour is followed
        # as-is, so the forest spills over to the North/West side where the terrain
        # actually rises. The roads and fields already keep clear of it via
        # is_in_forest(), and the infill pass below closes whatever is left over.
        add_way(list(poly), {
            'natural': 'wood',
            'landuse': 'farmyard',
            'leaf_type': 'needleleave'
        })
        print(f"   Added forest way {i+1} with {len(poly)} nodes.")

    # 11. Forest infill: absorb the leftover open ground next to the forests.
    # Everything generated so far is rasterised into an occupancy mask; whatever
    # is left unoccupied and sits next to a wood becomes forest too. Pockets on
    # the far side of the Southern Link Road qualify as well - a road splits the
    # empty ground into separate pockets and each one is judged on its own.
    INFILL_SCALE_M = 4.0        # raster resolution (metres per pixel)
    INFILL_MIN_RADIUS_M = 25.0  # a pocket must fit a disk of this radius to count
    INFILL_NEAR_M = 80.0        # ...and lie within this distance of an existing wood
    INFILL_SIMPLIFY_M = 8.0     # Douglas-Peucker tolerance for the emitted outlines
    ROAD_CORRIDOR_M = 15.0      # width reserved around linear features

    def disk_structure(radius_px):
        yy, xx = np.ogrid[-radius_px:radius_px+1, -radius_px:radius_px+1]
        return (xx*xx + yy*yy) <= radius_px*radius_px

    def simplify(points, tol):
        # Iterative Douglas-Peucker (the raster outlines are far too dense to keep)
        keep = np.zeros(len(points), dtype=bool)
        keep[0] = keep[-1] = True
        stack = [(0, len(points) - 1)]
        pts = np.asarray(points, dtype=float)
        while stack:
            i0, i1 = stack.pop()
            if i1 <= i0 + 1:
                continue
            a, b = pts[i0], pts[i1]
            seg = b - a
            seg_len = math.hypot(seg[0], seg[1])
            chunk = pts[i0+1:i1]
            if seg_len < 1e-9:
                d = np.hypot(chunk[:, 0] - a[0], chunk[:, 1] - a[1])
            else:
                d = np.abs(np.cross(seg, chunk - a)) / seg_len
            k = int(np.argmax(d))
            if d[k] > tol:
                k += i0 + 1
                keep[k] = True
                stack.append((i0, k))
                stack.append((k, i1))
        return [tuple(p) for p in pts[keep]]

    def build_infill_polygons():
        n = int(round(8192.0 / INFILL_SCALE_M))
        occ_img = Image.new('L', (n, n), 0)
        wood_img = Image.new('L', (n, n), 0)
        occ_draw = ImageDraw.Draw(occ_img)
        wood_draw = ImageDraw.Draw(wood_img)
        line_w = max(1, int(round(ROAD_CORRIDOR_M / INFILL_SCALE_M)))

        for w in ways:
            pts = [(x / INFILL_SCALE_M, y / INFILL_SCALE_M) for x, y in w['coords']]
            if len(pts) < 2:
                continue
            tags = w['tags']
            is_wood = tags.get('natural') == 'wood'
            if is_wood or 'landuse' in tags or tags.get('natural') == 'water':
                occ_draw.polygon(pts, fill=255, outline=255)
                if is_wood:
                    wood_draw.polygon(pts, fill=255, outline=255)
            else:
                occ_draw.line(pts, fill=255, width=line_w, joint='curve')

        void = np.array(occ_img) == 0
        wood = np.array(wood_img) > 0

        # Erode first: this drops the thin stuff (map margins, the strip along the
        # railway, verges) and keeps only pockets of genuinely open ground.
        disk = disk_structure(max(1, int(round(INFILL_MIN_RADIUS_M / INFILL_SCALE_M))))
        core = ndimage.binary_erosion(void, structure=disk)
        if not core.any():
            return ([], 0.0), ([], 0.0)

        # Judge each pocket as a whole: thick enough to have a core, and near a wood.
        lab, n_lab = ndimage.label(void)
        dist_m = ndimage.distance_transform_edt(~wood) * INFILL_SCALE_M
        near = np.atleast_1d(ndimage.minimum(dist_m, lab, range(1, n_lab + 1)))
        thick_ids = np.zeros(n_lab + 1, dtype=bool)
        thick_ids[np.unique(lab[core])] = True
        thick_ids[0] = False

        near_ids = np.concatenate(([False], near <= INFILL_NEAR_M)) & thick_ids
        far_ids = thick_ids & ~near_ids

        def trace(selected_ids):
            # Dilate the core back out so the pocket recovers its real outline while
            # the thin tentacles the erosion removed stay out of it.
            sel = selected_ids[lab]
            if not sel.any():
                return [], 0.0
            mask = ndimage.binary_dilation(core & sel, structure=disk) & sel
            area = mask.sum() * INFILL_SCALE_M**2 / 10000.0

            enclosed = ndimage.binary_fill_holes(mask) & ~mask
            if enclosed.any():
                print(f"   WARNING: infill pockets enclose "
                      f"{enclosed.sum() * INFILL_SCALE_M**2 / 10000.0:.1f} ha of occupied land; "
                      f"those holes get swallowed by the outline.")

            # Trace the outlines. Padding with a ring of zeros keeps every contour a
            # closed loop even where the pocket runs into the edge of the map.
            padded = np.zeros((n + 2, n + 2), dtype=np.float32)
            padded[1:-1, 1:-1] = mask
            axis = (np.arange(n + 2) - 0.5) * INFILL_SCALE_M
            gx, gy = np.meshgrid(axis, axis)

            fig, ax = plt.subplots()
            cs = ax.contour(gx, gy, padded, levels=[0.5])
            plt.close(fig)

            polygons = []
            for seg in cs.allsegs[0]:
                pts = [(min(max(px, 0.0), 8192.0), min(max(py, 0.0), 8192.0)) for px, py in seg]
                if pts[0] != pts[-1]:
                    pts.append(pts[0])
                pts = simplify(pts, INFILL_SIMPLIFY_M)
                if len(pts) < 4:
                    continue
                if pts[0] != pts[-1]:
                    pts.append(pts[0])
                polygons.append(pts)
            return polygons, area

        return trace(near_ids), trace(far_ids)

    print("   Filling unoccupied land next to the forests...")
    (wood_polys, wood_ha), (yard_polys, yard_ha) = build_infill_polygons()
    for i, poly in enumerate(wood_polys):
        add_way(poly, {
            'natural': 'wood',
            'landuse': 'farmyard',
            'leaf_type': 'needleleave',
            'name': f'Forest Infill {i+1}'
        })
    print(f"   Added {len(wood_polys)} infill forest areas covering {wood_ha:.1f} ha.")

    # Pockets too far from any wood to be absorbed by it stay open ground: they are
    # tagged farmyard only, so they read as yard rather than as forest or field.
    for i, poly in enumerate(yard_polys):
        add_way(poly, {
            'landuse': 'farmyard',
            'name': f'Open Ground {i+1}'
        })
    print(f"   Added {len(yard_polys)} leftover farmyard areas covering {yard_ha:.1f} ha.")

    # Generate XML
    osm_elem = ET.Element('osm', version='0.6', generator='Antigravity')
    
    # Add bounds
    ET.SubElement(osm_elem, 'bounds', {
        'minlat': f"{minlat:.10f}",
        'minlon': f"{minlon:.10f}",
        'maxlat': f"{maxlat:.10f}",
        'maxlon': f"{maxlon:.10f}"
    })

    # Add nodes
    sorted_node_ids = sorted(node_coords.keys())
    for nid in sorted_node_ids:
        lat, lon = node_coords[nid]
        ET.SubElement(osm_elem, 'node', {
            'id': str(nid),
            'lat': f"{lat:.10f}",
            'lon': f"{lon:.10f}",
            'version': '1',
            'timestamp': '2026-07-24T12:00:00Z',
            'changeset': '1',
            'uid': '1',
            'user': 'Antigravity'
        })

    # Add ways
    for way in ways:
        way_elem = ET.SubElement(osm_elem, 'way', {
            'id': str(way['id']),
            'version': '1',
            'timestamp': '2026-07-24T12:00:00Z',
            'changeset': '1',
            'uid': '1',
            'user': 'Antigravity'
        })
        for ref in way['node_refs']:
            ET.SubElement(way_elem, 'nd', ref=str(ref))
        for k, v in way['tags'].items():
            ET.SubElement(way_elem, 'tag', k=k, v=v)

    # Convert to pretty XML string
    xml_str = ET.tostring(osm_elem, encoding='utf-8')
    parsed_xml = minidom.parseString(xml_str)
    pretty_xml = parsed_xml.toprettyxml(indent='  ', encoding='utf-8')

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, "map.osm")
    
    with open(output_path, "wb") as f:
        f.write(pretty_xml)

    print(f"[+] Successfully wrote {len(node_coords)} nodes and {len(ways)} ways to '{output_path}'.")

if __name__ == '__main__':
    main()
