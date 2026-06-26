import random
import math
import xml.etree.ElementTree as ET
from xml.dom import minidom
import os

# --- Configurations ---
random.seed(20240605)

S = 8192                      # canvas px
MILES = 8                     # real miles across
PPM = S / MILES               # px per mile = 1024
def m(x): return x * PPM      # helper for miles

def get_road_x(y):
    y_miles = y / PPM
    if y_miles <= 2.2:
        x_miles = 7.0
    elif y_miles <= 3.8:
        u = (y_miles - 2.2) / (3.8 - 2.2)
        x_miles = 4.0 + 3.0 * (1.0 + math.cos(math.pi * u)) / 2.0
    elif y_miles <= 4.2:
        x_miles = 4.0
    elif y_miles <= 5.8:
        u = (y_miles - 4.2) / (5.8 - 4.2)
        x_miles = 1.0 + 3.0 * (1.0 + math.cos(math.pi * u)) / 2.0
    else:
        x_miles = 1.0
    return m(x_miles)

def crosses_diagonal_forest(x0, y0, x1, y1):
    if y1 <= m(1) or y0 >= m(7):
        return False
    y_start = max(y0, m(1))
    y_end = min(y1, m(7))
    for y in [y_start, (y_start + y_end)/2, y_end]:
        rx = get_road_x(y)
        if x0 - 1255 <= rx <= x1 + 1255:
            return True
    return False



def get_forest_top(x):
    y_c = m(0.35) + (m(0.1) * (x / S)) + 90 * math.sin(x * 2 * math.pi / 3200) + 25 * math.sin(x * 2 * math.pi / 900)
    w = 180 + 30 * math.sin(x * 2 * math.pi / 1000)
    return y_c - w/2

def get_forest_bottom(x):
    y_c = m(0.35) + (m(0.1) * (x / S)) + 90 * math.sin(x * 2 * math.pi / 3200) + 25 * math.sin(x * 2 * math.pi / 900)
    w = 180 + 30 * math.sin(x * 2 * math.pi / 1000)
    return y_c + w/2

def get_shrunk_x(x0, x1):
    if x0 == 0:
        x0_s = 100
    elif x0 == 1024:
        x0_s = 1024 + 23
    else:
        x0_s = x0 + 16
        
    if x1 == 8192:
        x1_s = 8192 - 100
    elif x1 == 1024:
        x1_s = 1024 - 23
    else:
        x1_s = x1 - 16
        
    return x0_s, x1_s

TH_P = 22                     # primary
TH_S = 16                     # secondary
TH_T = 8                      # track
GAP = 40                      # Greater separation between polygons and roads
W_ROAD_BORDER = 12            # Black border/margin for roads
W_CANAL_BORDER = 12           # Black border/margin for canals
CW = 26                       # Canal width
off = TH_T/2 + CW/2 + GAP


# Lake and road loop definitions removed

# --- Georeferencing ---
# Center: (27.07991, -109.70707)
min_lon = -109.748441630125
min_lat = 27.043073839058213
max_lon = -109.665698369875
max_lat = 27.11674616094179

def to_gps(x, y):
    lon = min_lon + (x / S) * (max_lon - min_lon)
    lat = max_lat - (y / S) * (max_lat - min_lat)
    return lat, lon

# --- Node & Way Registries ---
node_id_counter = 1
way_id_counter = 1
node_map = {}     # (rounded_x, rounded_y) -> node_id
node_coords = {}  # node_id -> (lat, lon)
ways = []         # list of dict: {'id': int, 'nodes': [int], 'tags': dict}

def get_node(x, y):
    global node_id_counter
    # Key by coordinate rounded to 2 decimal places in pixel space to ensure topological connection
    key = (round(x, 2), round(y, 2))
    if key not in node_map:
        node_map[key] = node_id_counter
        lat, lon = to_gps(x, y)
        node_coords[node_id_counter] = (lat, lon)
        node_id_counter += 1
    return node_map[key]

def create_unique_node(x, y):
    global node_id_counter
    nid = node_id_counter
    lat, lon = to_gps(x, y)
    node_coords[nid] = (lat, lon)
    node_id_counter += 1
    return nid

def add_way(nodes_list, tags):
    global way_id_counter
    ways.append({
        'id': way_id_counter,
        'nodes': nodes_list,
        'tags': tags
    })
    way_id_counter += 1

# ================= 1. FIELDS (Farmland Parcels) =================
parcels = []
def in_town(cx, cy):
    return m(1) <= cx < m(2) and m(1) <= cy < m(2)

def split_block(x0, y0, x1, y1, depth, edge, near_town):
    w = x1 - x0
    h = y1 - y0
    
    maxdepth = 1
        
    if depth >= 1 and random.random() < 0.52:
        parcels.append((x0, y0, x1, y1))
        return
        
    if depth >= maxdepth or (w < m(0.15) or h < m(0.15)):
        parcels.append((x0, y0, x1, y1))
        return
        
    r = random.uniform(0.3, 0.7)
    if w >= h:
        xm = x0 + w * r
        split_block(x0, y0, xm, y1, depth + 1, edge, near_town)
        split_block(xm, y0, x1, y1, depth + 1, edge, near_town)
    else:
        ym = y0 + h * r
        split_block(x0, y0, x1, ym, depth + 1, edge, near_town)
        split_block(x0, ym, x1, y1, depth + 1, edge, near_town)

for i in range(MILES):
    for j in range(MILES):
        x0, y0 = m(i), m(j)
        x1, y1 = m(i+1), m(j+1)
        cx, cy = (x0+x1)/2, (y0+y1)/2
        
        is_north = (j == 0)
        if is_north:
            if i >= 4:
                # East half: long fields from east to west (no x_mid split)
                for r in range(4):
                    y_start = y0 + r * 256
                    y_end = y_start + 256
                    parcels.append((x0, y_start, x1, y_end))
            else:
                # West half: standard split
                x_mid = x0 + 512
                for r in range(4):
                    y_start = y0 + r * 256
                    y_end = y_start + 256
                    parcels.append((x0, y_start, x_mid, y_end))
                    parcels.append((x_mid, y_start, x1, y_end))
            continue
            
        if i == 1 and j == 1:
            # Divide the southern half of the town section into 4 equal-sized fields (2x2 grid)
            parcels.append((m(1.0), m(1.5), m(1.5), m(1.75)))
            parcels.append((m(1.5), m(1.5), m(2.0), m(1.75)))
            parcels.append((m(1.0), m(1.75), m(1.5), m(2.0)))
            parcels.append((m(1.5), m(1.75), m(2.0), m(2.0)))
            continue
            
        if in_town(cx, cy):
            continue

        near_town = (abs(i - 1.5) <= 1.5 and abs(j - 1.5) <= 1.5 and j > 0)
        along_canal = (i == 2 and (1 <= j <= 6)) or (j == 2 and (1 <= i <= 6))
        is_south = (j == MILES - 1)
        is_southeast_circle = (i in [3, 4, 5, 6] and j == 5)
        
        if is_south or is_southeast_circle:
            continue
            
        if crosses_diagonal_forest(x0, y0, x1, y1):
            parcels.append((x0, y0, x1, y1))
            continue
            
        if not (near_town or along_canal):
            parcels.append((x0, y0, x1, y1))
            continue
            
        edge = (i == 0 or i == MILES - 1 or j == 0 or j == MILES - 1)
        split_block(x0, y0, x1, y1, 0, edge, near_town)

# --- Geometries with GAP adjustments ---
TOWN_X0, TOWN_X1, TOWN_Y0, TOWN_Y1 = m(1), m(2), m(1), m(2)

forests = [
    (m(2.0), m(1.0), m(2.25), m(2.0)),
    (3782, 7168, 4410, 8092) # Southern forest surrounding the farmyard, reaching both edges
]

diag_forests = []

yards = [
    (m(4.375), m(1) + TH_P/2, m(4.625), m(1) + TH_P/2 + m(0.25)),
    (m(2.35), m(7) - TH_P/2 - m(0.3), m(2.65), m(7) - TH_P/2),
    (m(4.4), m(7) - TH_P/2 - m(0.2), m(4.6), m(7) - TH_P/2),
    (m(6.35), m(7) - TH_P/2 - m(0.3), m(6.65), m(7) - TH_P/2),
    (m(1) + TH_P/2, m(4.4), m(1) + TH_P/2 + m(0.2), m(4.6)),
    (m(1.625), m(1.0), m(2.0), m(1.5)),
    (m(7) - TH_P/2 - m(0.5), m(4.25), m(7) - TH_P/2, m(4.75)),
    (3846, 7380, 4346, 7880) # Southern Yard: 500x500px in the middle of southern zone
]

# get_road_x defined at the top of the file

num_forest_steps = 240
for i in range(num_forest_steps):
    y0 = m(1.0 + i * (6.0 / num_forest_steps))
    y1 = m(1.0 + (i + 1) * (6.0 / num_forest_steps))
    ym = (y0 + y1) / 2
    xc = get_road_x(ym)
    x0 = max(100.0, xc - 1255.0)
    x1 = min(S - 100.0, xc + 1255.0)
    diag_forests.append((x0, y0, x1, y1))

def find_intersection_y(target_x):
    low = m(1)
    high = m(7)
    for _ in range(20):
        mid = (low + high) / 2
        x = get_road_x(mid)
        if x > target_x:
            low = mid
        else:
            high = mid
    # Clean up boundary cases to avoid duplicate nodes at intersections
    if abs(mid - m(1)) < 1.0:
        return m(1)
    if abs(mid - m(7)) < 1.0:
        return m(7)
    return mid

def get_diag_spot(y_c, side):
    x_c = get_road_x(y_c)
    w = m(0.125)
    h = m(0.125)
    if side == 'northeast':
        x0 = x_c + TH_P/2
        x1 = x0 + w
    else:
        x1 = x_c - TH_P/2
        x0 = x1 - w
    y0 = y_c - h/2
    y1 = y_c + h/2
    return (x0, y0, x1, y1)

ind_spots = [
    # Road 1: Horizontal y=1, south side (5 zones placed in field corners)
    (m(3) - TH_T/2 - m(0.125), m(1) + TH_P/2, m(3) - TH_T/2, m(1) + TH_P/2 + m(0.125)),
    (m(3) + TH_T/2, m(1) + TH_P/2, m(3) + TH_T/2 + m(0.125), m(1) + TH_P/2 + m(0.125)),
    (m(4) - TH_T/2 - m(0.125), m(1) + TH_P/2, m(4) - TH_T/2, m(1) + TH_P/2 + m(0.125)),
    (m(5) - TH_T/2 - m(0.125), m(1) + TH_P/2, m(5) - TH_T/2, m(1) + TH_P/2 + m(0.125)),
    (m(6) - TH_T/2 - m(0.125), m(1) + TH_P/2, m(6) - TH_T/2, m(1) + TH_P/2 + m(0.125)),
    
    # Road 2: Horizontal y=7, north side (5 zones placed in field corners)
    (m(2) + TH_T/2, m(7) - TH_P/2 - m(0.125), m(2) + TH_T/2 + m(0.125), m(7) - TH_P/2),
    (m(3) + TH_T/2, m(7) - TH_P/2 - m(0.125), m(3) + TH_T/2 + m(0.125), m(7) - TH_P/2),
    (m(4) + TH_T/2, m(7) - TH_P/2 - m(0.125), m(4) + TH_T/2 + m(0.125), m(7) - TH_P/2),
    (m(5) + TH_T/2, m(7) - TH_P/2 - m(0.125), m(5) + TH_T/2 + m(0.125), m(7) - TH_P/2),
    (m(6) - TH_T/2 - m(0.125), m(7) - TH_P/2 - m(0.125), m(6) - TH_T/2, m(7) - TH_P/2),
]

# --- Farmland Clipping Geometry ---
clips = []
# 100m unassigned border clip
clips.append((0, 0, S, 100))
clips.append((0, S - 100, S, S))
clips.append((0, 0, 100, S))
clips.append((S - 100, 0, S, S))



clips.append((m(1.0), m(1.0), m(1.625), m(1.5))) # Top-west of town
for f in forests:
    clips.append(f)
# diag_forests handled directly with curve clipping
for y in yards:
    clips.append(y)
for ind in ind_spots:
    clips.append(ind)

# Add road footprints to clips to separate farmlands from roads
for k in range(1, MILES):
    y = m(k)
    hw = TH_P/2 + W_ROAD_BORDER if (k == 1 or k == 7) else TH_T/2 + W_ROAD_BORDER
    clips.append((0, y - hw, S, y + hw))

for k in range(1, MILES):
    x = m(k)
    hw = TH_T/2 + W_ROAD_BORDER
    y_start = m(1)
    clips.append((x - hw, y_start, x + hw, m(7) + W_ROAD_BORDER))

# Diagonal primary road is entirely inside the diagonal forest buffer, so we don't clip farmlands against it.


# Add southern track footprints to clips
hw_track = TH_T/2 + W_ROAD_BORDER
clips.append((4096 - hw_track, 7168 - hw_track, 4096 + hw_track, 8040 + hw_track))
clips.append((100, 8040 - hw_track, 8092, 8040 + hw_track))



def subtract_single(A, B):
    ax0, ay0, ax1, ay1 = A
    bx0, by0, bx1, by1 = B
    
    # Find intersection region
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    
    # Check if there is a valid intersection
    if ix0 >= ix1 or iy0 >= iy1:
        return [A]
        
    parts = []
    # 1. Top region
    if ay0 < iy0:
        parts.append((ax0, ay0, ax1, iy0))
    # 2. Bottom region
    if iy1 < ay1:
        parts.append((ax0, iy1, ax1, ay1))
    # 3. Left region
    if ax0 < ix0:
        parts.append((ax0, iy0, ix0, iy1))
    # 4. Right region
    if ix1 < ax1:
        parts.append((ix1, iy0, ax1, iy1))
        
    # Return only sub-rectangles with positive area (avoiding 1px/0px slivers from rounding)
    return [p for p in parts if (p[2] - p[0] > 1.0 and p[3] - p[1] > 1.0)]

def subtract_rects(subject, clip_list):
    current_rects = [subject]
    for clip in clip_list:
        next_rects = []
        for r in current_rects:
            next_rects.extend(subtract_single(r, clip))
        current_rects = next_rects
    return current_rects

# Add parcels as ways, clipping them with other area elements first
for p in parcels:
    x0, y0, x1, y1 = p
    clipped_parts = subtract_rects(p, clips)
    for (cx0, cy0, cx1, cy1) in clipped_parts:
        # Shrink by 6 pixels on each side to create a margin and avoid node sharing
        margin = 6
        cx0_s = cx0 + margin
        cx1_s = cx1 - margin
        cy0_s = cy0 + margin
        cy1_s = cy1 - margin
        
        # Avoid invalid geometries for tiny slivers (less than 10 meters wide/tall)
        if cx1_s - cx0_s <= 10.0 or cy1_s - cy0_s <= 10.0:
            continue
            
        in_forest_range = (cy0_s < m(7)) and (cy1_s > m(1))
        if not in_forest_range:
            ns = [
                create_unique_node(cx0_s, cy0_s),
                create_unique_node(cx1_s, cy0_s),
                create_unique_node(cx1_s, cy1_s),
                create_unique_node(cx0_s, cy1_s),
            ]
            ns.append(ns[0])
            add_way(ns, {'landuse': 'farmland'})
            continue
            
        # Clip the shrunk rectangle with the diagonal forest (1255px margin from road center to cover 1000m hills + 5m gap)
        # Sample every 16px along the y range to get a smooth curve
        y_vals = []
        y_curr = cy0_s
        while y_curr < cy1_s:
            y_vals.append(y_curr)
            y_curr += 16
        y_vals.append(cy1_s)
        
        has_left = False
        has_right = False
        for y_val in y_vals:
            L_y = get_road_x(y_val) - 1255.0
            R_y = get_road_x(y_val) + 1255.0
            if cx0_s < L_y:
                has_left = True
            if cx1_s > R_y:
                has_right = True
                
        # Generate left polygon nodes
        if has_left:
            valid_y_vals = [y for y in y_vals if get_road_x(y) - 1255.0 > cx0_s]
            if len(valid_y_vals) >= 2:
                y_start = valid_y_vals[0]
                y_end = valid_y_vals[-1]
                pts = [(cx0_s, y_start), (cx0_s, y_end)]
                for y_val in reversed(valid_y_vals):
                    L_y = get_road_x(y_val) - 1255.0
                    px = max(cx0_s, min(cx1_s, L_y))
                    if pts[-1] != (px, y_val):
                        pts.append((px, y_val))
                if pts[-1] != pts[0]:
                    pts.append(pts[0])
                    
                if len(pts) >= 4:
                    xs = [pt[0] for pt in pts]
                    ys = [pt[1] for pt in pts]
                    if (max(xs) - min(xs) > 10.0) and (max(ys) - min(ys) > 10.0):
                        ns = [create_unique_node(x, y) for (x, y) in pts[:-1]]
                        ns.append(ns[0])
                        add_way(ns, {'landuse': 'farmland'})
                        
        # Generate right polygon nodes
        if has_right:
            valid_y_vals = [y for y in y_vals if get_road_x(y) + 1255.0 < cx1_s]
            if len(valid_y_vals) >= 2:
                y_start = valid_y_vals[0]
                y_end = valid_y_vals[-1]
                pts = [(cx1_s, y_start)]
                for y_val in valid_y_vals:
                    R_y = get_road_x(y_val) + 1255.0
                    px = max(cx0_s, min(cx1_s, R_y))
                    if pts[-1] != (px, y_val):
                        pts.append((px, y_val))
                if pts[-1] != (cx1_s, y_end):
                    pts.append((cx1_s, y_end))
                if pts[-1] != pts[0]:
                    pts.append(pts[0])
                    
                if len(pts) >= 4:
                    xs = [pt[0] for pt in pts]
                    ys = [pt[1] for pt in pts]
                    if (max(xs) - min(xs) > 10.0) and (max(ys) - min(ys) > 10.0):
                        ns = [create_unique_node(x, y) for (x, y) in pts[:-1]]
                        ns.append(ns[0])
                        add_way(ns, {'landuse': 'farmland'})

# ================= Southern Zone Fields in OSM =================
# West: 5 circular fields + 2 square fields + 2 columns of 2x2 split fields in 2 rows, East: horizontal thin strips split in 2x4
y_start = 7208
y_end = 8008
x_min = 100
x_max = 3782
N_cols_s = 9
N_rows_s = 2
R_s = 190
margin = 6

col_width = (x_max - x_min) / N_cols_s
row_height = (y_end - y_start) / N_rows_s

for r in range(N_rows_s):
    cy = y_start + row_height / 2 + r * row_height
    y0 = y_start + r * row_height
    y1 = y0 + row_height
    for c in range(N_cols_s):
        x0 = x_min + c * col_width
        x1 = x0 + col_width
        cx = x_min + col_width / 2 + c * col_width
        
        if c < 5:
            # Square farmland replacing circle approximation
            cx0_s = cx - R_s + margin
            cx1_s = cx + R_s - margin
            cy0_s = cy - R_s + margin
            cy1_s = cy + R_s - margin
            
            ns = [
                create_unique_node(cx0_s, cy0_s),
                create_unique_node(cx1_s, cy0_s),
                create_unique_node(cx1_s, cy1_s),
                create_unique_node(cx0_s, cy1_s),
            ]
            ns.append(ns[0])
            add_way(ns, {'landuse': 'farmland'})
        elif c in [5, 6]:
            # Rectangle (square farmland)
            cx0_s = x0 + margin
            cx1_s = x1 - margin
            cy0_s = y0 + margin
            cy1_s = y1 - margin
            
            ns = [
                create_unique_node(cx0_s, cy0_s),
                create_unique_node(cx1_s, cy0_s),
                create_unique_node(cx1_s, cy1_s),
                create_unique_node(cx0_s, cy1_s),
            ]
            ns.append(ns[0])
            add_way(ns, {'landuse': 'farmland'})
        else:
            # Columns 7 and 8: split into 2x2 grid of smaller squares
            sub_w = col_width / 2
            sub_h = row_height / 2
            for sr in range(2):
                sy0 = y0 + sr * sub_h
                sy1 = sy0 + sub_h
                for sc in range(2):
                    sx0 = x0 + sc * sub_w
                    sx1 = sx0 + sub_w
                    
                    cx0_s = sx0 + margin
                    cx1_s = sx1 - margin
                    cy0_s = sy0 + margin
                    cy1_s = sy1 - margin
                    
                    ns = [
                        create_unique_node(cx0_s, cy0_s),
                        create_unique_node(cx1_s, cy0_s),
                        create_unique_node(cx1_s, cy1_s),
                        create_unique_node(cx0_s, cy1_s),
                    ]
                    ns.append(ns[0])
                    add_way(ns, {'landuse': 'farmland'})

x_min_h = 4410
x_max_h = 8092
N_cols = 2
N_rows = 4
width_col = (x_max_h - x_min_h) / N_cols
height_row = (y_end - y_start) / N_rows

for c in range(N_cols):
    col_x0 = x_min_h + c * width_col
    col_x1 = col_x0 + width_col
    for r in range(N_rows):
        row_y0 = y_start + r * height_row
        row_y1 = row_y0 + height_row
        
        cx0_s = col_x0 + margin
        cx1_s = col_x1 - margin
        cy0_s = row_y0 + margin
        cy1_s = row_y1 - margin
        
        ns = [
            create_unique_node(cx0_s, cy0_s),
            create_unique_node(cx1_s, cy0_s),
            create_unique_node(cx1_s, cy1_s),
            create_unique_node(cx0_s, cy1_s),
        ]
        ns.append(ns[0])
        add_way(ns, {'landuse': 'farmland'})

# ================= Southeast Circular Fields in OSM =================
for col, row in [(3, 5), (4, 5), (5, 5), (6, 5)]:
    cx = col * 1024 + 512
    cy = row * 1024 + 512
    R = 472
    cx0_s = cx - R + margin
    cx1_s = cx + R - margin
    cy0_s = cy - R + margin
    cy1_s = cy + R - margin
    ns = [
        create_unique_node(cx0_s, cy0_s),
        create_unique_node(cx1_s, cy0_s),
        create_unique_node(cx1_s, cy1_s),
        create_unique_node(cx0_s, cy1_s),
    ]
    ns.append(ns[0])
    add_way(ns, {'landuse': 'farmland'})



# ================= 2. TOWN =================

town_nodes = [
    create_unique_node(m(1.0), m(1.0)),
    create_unique_node(m(1.625), m(1.0)),
    create_unique_node(m(1.625), m(1.5)),
    create_unique_node(m(1.0), m(1.5)),
]
town_nodes.append(town_nodes[0])
add_way(town_nodes, {'landuse': 'residential'})

# Town streets (Grid of 8x8 blocks, meaning 7 internal streets in each direction)
# Vertical streets
for i in range(1, 5):
    x = TOWN_X0 + i * (TOWN_X1 - TOWN_X0) / 8
    # Form street segments connected with intersections
    pts = [TOWN_Y0 + m(0.05)] + [TOWN_Y0 + j * (TOWN_Y1 - TOWN_Y0) / 8 for j in range(1, 4)] + [m(1.5)]
    ns = [get_node(x, y_val) for y_val in pts]
    add_way(ns, {'highway': 'residential'})

# Horizontal streets
for j in range(1, 4):
    y = TOWN_Y0 + j * (TOWN_Y1 - TOWN_Y0) / 8
    pts = [TOWN_X0 + m(0.05)] + [TOWN_X0 + i * (TOWN_X1 - TOWN_X0) / 8 for i in range(1, 5)] + [m(1.625)]
    ns = [get_node(x_val, y) for x_val in pts]
    add_way(ns, {'highway': 'residential'})

# ================= 3. FORESTS =================

for (x0, y0, x1, y1) in forests:
    ns = [
        create_unique_node(x0, y0),
        create_unique_node(x1, y0),
        create_unique_node(x1, y1),
        create_unique_node(x0, y1),
    ]
    ns.append(ns[0])
    add_way(ns, {'landuse': 'farmyard', 'natural': 'wood', 'leaf_type': 'broadleaf'})

# 10 separate sections of the diagonal forest (covering 1000m wide hills)
forest_sections = [
    (1024.0, 1324.0), # size: 300m
    (1329.0, 1829.0), # size: 500m
    (1834.0, 2584.0), # size: 750m
    (2589.0, 3489.0), # size: 900m
    (3494.0, 3844.0), # size: 350m
    (3849.0, 4449.0), # size: 600m
    (4454.0, 5254.0), # size: 800m
    (5259.0, 5709.0), # size: 450m
    (5714.0, 6364.0), # size: 650m
    (6369.0, 7168.0)  # size: 799m
]

for idx, (y0, y1) in enumerate(forest_sections):
    forest_nodes = []
    
    # Right side: from top to bottom
    y_right = list(range(int(y0), int(y1) + 1, 32))
    if y_right[-1] != int(y1):
        y_right.append(int(y1))
    for y_px in y_right:
        xc = get_road_x(y_px)
        xr = min(S - 100.0, xc + 1250.0)
        forest_nodes.append(create_unique_node(xr, y_px))
        
    # Left side: from bottom to top
    y_left = list(range(int(y1), int(y0) - 1, -32))
    if y_left[-1] != int(y0):
        y_left.append(int(y0))
    for y_px in y_left:
        xc = get_road_x(y_px)
        xl = max(100.0, xc - 1250.0)
        forest_nodes.append(create_unique_node(xl, y_px))
        
    # Close the polygon
    forest_nodes.append(forest_nodes[0])
    
    # Add the forest way
    add_way(forest_nodes, {
        'landuse': 'farmyard',
        'natural': 'wood',
        'leaf_type': 'broadleaf',
        'name': f'Bosque de la Diagonal - Sección {idx+1}'
    })

# Lake and railway tracks removed

# ================= 4. FARMYARDS =================

for (x0, y0, x1, y1) in yards:
    ns = [
        create_unique_node(x0, y0),
        create_unique_node(x1, y0),
        create_unique_node(x1, y1),
        create_unique_node(x0, y1),
    ]
    ns.append(ns[0])
    add_way(ns, {'landuse': 'farmyard'})

# ================= 5. INDUSTRIAL SPOTS =================

for (x0, y0, x1, y1) in ind_spots:
    ns = [
        create_unique_node(x0, y0),
        create_unique_node(x1, y0),
        create_unique_node(x1, y1),
        create_unique_node(x0, y1),
    ]
    ns.append(ns[0])
    add_way(ns, {'landuse': 'farmyard', 'building': 'industrial'})



# Canals, reservoirs, and river removed as per request

# ================= 8. ROADS =================
# Horizontal roads
for k in range(1, MILES):
    y = m(k)
    if k == 1 or k == 7:
        # Primary roads cross the forest: keep as a single way, but clean duplicates
        coords = sorted(list(set([m(i) for i in range(MILES+1)] + [get_road_x(y)])))
        ns = [get_node(x, y) for x in coords]
        add_way(ns, {'highway': 'primary'})
    else:
        # Track roads (cut diagonal forest)
        xc = get_road_x(y)
        x_L = xc - 1255.0
        x_R = xc + 1255.0
        coords = [m(i) for i in range(MILES+1)]
        
        # Left segment
        coords_L = sorted(list(set([x for x in coords if x < x_L] + [x_L])))
        if len(coords_L) >= 2:
            ns_L = [get_node(x, y) for x in coords_L]
            add_way(ns_L, {'highway': 'track'})
            
        # Right segment
        coords_R = sorted(list(set([x_R] + [x for x in coords if x > x_R])))
        if len(coords_R) >= 2:
            ns_R = [get_node(x, y) for x in coords_R]
            add_way(ns_R, {'highway': 'track'})
 
# Vertical roads
for k in range(1, MILES):
    x = m(k)
    # All vertical roads are track roads, cut around diagonal forest
    y_enter = 1024.0 if (x + 1255.0 > 7168.0) else find_intersection_y(x + 1255.0)
    y_exit = 7168.0 if (x - 1255.0 < 1024.0) else find_intersection_y(x - 1255.0)
    y_coords = [m(j) for j in range(1, 8)]
    
    # Top segment
    y_coords_top = sorted(list(set([y for y in y_coords if y < y_enter] + [y_enter])))
    if y_enter > 1024.0 and len(y_coords_top) >= 2:
        ns_top = [get_node(x, y) for y in y_coords_top]
        add_way(ns_top, {'highway': 'track'})
        
    # Bottom segment
    y_coords_bottom = sorted(list(set([y_exit] + [y for y in y_coords if y > y_exit])))
    if y_exit < 7168.0 and len(y_coords_bottom) >= 2:
        ns_bottom = [get_node(x, y) for y in y_coords_bottom]
        add_way(ns_bottom, {'highway': 'track'})
 
# Diagonal primary road
diag_pts = []
for k in range(49):
    y_val = m(1) + k * 128
    x_val = get_road_x(y_val)
    diag_pts.append((x_val, y_val))
 
for k in range(1, MILES):
    x_int = m(k)
    y_int = find_intersection_y(x_int)
    diag_pts.append((x_int, y_int))
 
# Sort points by y coordinate and remove duplicates
diag_pts = sorted(list(set(diag_pts)), key=lambda p: p[1])
diag_nodes = [get_node(x, y) for (x, y) in diag_pts]
add_way(diag_nodes, {'highway': 'primary'})
 
 
 
# Southern track roads (cut around southern forest: x in [3782, 4410], y in [7168, 8092])
# south_vertical_track is entirely inside/close to the forest, so it is removed.
# south_horizontal_track is cut 5m from the forest (margin at 3777 and 4415)
south_horizontal_track_L = [
    get_node(100, 8040),
    get_node(3777, 8040)
]
add_way(south_horizontal_track_L, {'highway': 'track', 'name': 'Camino de Terracería Costero'})
 
south_horizontal_track_R = [
    get_node(4415, 8040),
    get_node(8092, 8040)
]
add_way(south_horizontal_track_R, {'highway': 'track', 'name': 'Camino de Terracería Costero'})



# ================= 9. BUILD OSM XML =================
root = ET.Element('osm', {
    'version': '0.6',
    'generator': 'osm_generator_py'
})

# Bounds
ET.SubElement(root, 'bounds', {
    'minlat': str(min_lat),
    'minlon': str(min_lon),
    'maxlat': str(max_lat),
    'maxlon': str(max_lon)
})

# Nodes
# Sort keys to make the XML deterministic
sorted_node_ids = sorted(node_coords.keys())
for nid in sorted_node_ids:
    lat, lon = node_coords[nid]
    ET.SubElement(root, 'node', {
        'id': str(nid),
        'lat': f"{lat:.8f}",
        'lon': f"{lon:.8f}",
        'version': '1',
        'changeset': '1',
        'user': 'osm_generator',
        'uid': '1',
        'timestamp': '2026-06-02T00:00:00Z'
    })

# Ways
for w in ways:
    w_el = ET.SubElement(root, 'way', {
        'id': str(w['id']),
        'version': '1',
        'changeset': '1',
        'user': 'osm_generator',
        'uid': '1',
        'timestamp': '2026-06-02T00:00:00Z'
    })
    for ref in w['nodes']:
        ET.SubElement(w_el, 'nd', {
            'ref': str(ref)
        })
    for k, v in w['tags'].items():
        ET.SubElement(w_el, 'tag', {
            'k': k,
            'v': v
        })

# Format and write
os.makedirs("outputs", exist_ok=True)
xml_str = ET.tostring(root, encoding='utf-8')
parsed = minidom.parseString(xml_str)
pretty_xml = parsed.toprettyxml(indent="  ")

# Remove blank lines introduced by toprettyxml inside elements if any
cleaned_lines = [line for line in pretty_xml.split('\n') if line.strip() != ""]
cleaned_xml = '\n'.join(cleaned_lines)

output_file = "outputs/zoning_map.osm"
with open(output_file, "w", encoding="utf-8") as f:
    f.write(cleaned_xml)

print(f"OSM file successfully written to {output_file}")
print(f"Generated {len(node_coords)} nodes and {len(ways)} ways.")
