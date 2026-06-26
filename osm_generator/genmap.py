import random
import math
from PIL import Image, ImageDraw

random.seed(20240605)

S = 8192                      # canvas px
MILES = 8                     # real miles across (PLSS scale)
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
        if x0 - 1300 <= rx <= x1 + 1300:
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

# ---- palette ----
C_FARM   = (150,168,88)
C_FARMB  = (0,0,0)
C_ROADP  = (240,200,30)       # Amarillo para caminos principales
C_ROADS  = (175,95,40)
C_ROADT  = (120,120,124)
C_WATER  = (54,110,168)
C_FOREST = (38,74,44)
C_RES    = (170,78,70)
C_RESST  = (225,225,220)
C_YARD   = (110,80,120)
C_YARDB  = (60,42,72)
C_IND    = (90,96,110)

# ---- configuration for road widths, borders and gaps ----
TH_P = 22                     # primary road thickness
TH_S = 16                     # secondary road thickness
TH_T = 8                      # track road thickness
W_FIELD_BORDER = 12           # Thicker black lines for fields (originally 1)
GAP = 40                      # Greater separation between polygons and roads (originally 5 for yards)
W_ROAD_BORDER = 12            # Black border/margin for roads
W_CANAL_BORDER = 12           # Black border/margin for canals


img = Image.new("RGB",(S,S),C_FARM)
d = ImageDraw.Draw(img)

def rect(x0,y0,x1,y1,fill,outline=None,width=0):
    d.rectangle([x0,y0,x1,y1],fill=fill,outline=outline,width=width)

# ================= FIELDS (Farmland Parcels) =================
# Subdivide sections into rectangular fields using PLSS binary subdivisions.
# Town block is skipped.
def in_town(cx, cy):
    return m(1) <= cx < m(2) and m(1) <= cy < m(2)

parcels = []
def split_block(x0, y0, x1, y1, depth, edge, near_town):
    w = x1 - x0
    h = y1 - y0
    
    maxdepth = 1
        
    # Introduce early stopping to create a mix of large and small fields
    if depth >= 1 and random.random() < 0.52:
        parcels.append((x0, y0, x1, y1))
        return
        
    if depth >= maxdepth or (w < m(0.15) or h < m(0.15)):
        parcels.append((x0, y0, x1, y1))
        return
        
    # Split using a random ratio to create diverse sizes (rectangular and square)
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
            continue  # Skip town block, drawn later

        near_town = (abs(i - 1.5) <= 1.5 and abs(j - 1.5) <= 1.5 and j > 0)
        along_canal = (i == 2 and (1 <= j <= 6)) or (j == 2 and (1 <= i <= 6))
        is_south = (j == MILES - 1)
        
        if is_south:
            continue
            
        if crosses_diagonal_forest(x0, y0, x1, y1):
            continue
            
        if not (near_town or along_canal):
            continue  # Draw farmlands near town or along canals
            
        edge = (i == 0 or i == MILES - 1 or j == 0 or j == MILES - 1)
        split_block(x0, y0, x1, y1, 0, edge, near_town)

# Draw farmland and rice parcels with a simple single dividing line (no margins, W_FIELD_BORDER px border)
C_FARMB = (0,0,0)
C_RICE = (115, 165, 135)  # Flooded rice paddy color (blend of blue-green)

for (x0, y0, x1, y1) in parcels:
    cx0 = max(100, x0)
    cy0 = max(100, y0)
    cx1 = min(S - 100, x1)
    cy1 = min(S - 100, y1)
    if cx1 - cx0 > 20 and cy1 - cy0 > 20:
        fill_col = C_RICE if (y0 >= m(7) or y0 < m(1)) else C_FARM
        rect(cx0, cy0, cx1, cy1, fill_col, outline=C_FARMB, width=W_FIELD_BORDER)

# Southern Zone Fields (West: 5 circular fields + 2 square fields + 2 columns of 2x2 split fields in 2 rows, East: horizontal thin strips split in 2x4)
y_start = 7208
y_end = 8008
x_min = 100
x_max = 3782
N_cols_s = 9
N_rows_s = 2
R_s = 190

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
            rect(cx - R_s, cy - R_s, cx + R_s, cy + R_s, C_FARM, outline=C_FARMB, width=W_FIELD_BORDER)
        elif c in [5, 6]:
            rect(x0, y0, x1, y1, C_FARM, outline=C_FARMB, width=W_FIELD_BORDER)
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
                    rect(sx0, sy0, sx1, sy1, C_FARM, outline=C_FARMB, width=W_FIELD_BORDER)

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
        rect(col_x0, row_y0, col_x1, row_y1, C_FARM, outline=C_FARMB, width=W_FIELD_BORDER)

# Southeast circular fields
for col, row in [(3, 5), (4, 5), (5, 5), (6, 5)]:
    cx = col * 1024 + 512
    cy = row * 1024 + 512
    R = 472
    rect(cx - R, cy - R, cx + R, cy + R, C_FARM, outline=C_FARMB, width=W_FIELD_BORDER)






# ================= LAKE (200 hectares irregular lake in the north) =================
# Lake, lake farmyard, road loop, and railway removed as requested


# Merge a few adjacent parcels to create L-shaped fields by erasing their shared boundary
def draw_L():
    if len(parcels) < 2: return
    a = random.choice(parcels)
    cx = (a[0] + a[2]) / 2
    cy = (a[1] + a[3]) / 2
    if a[1] < m(1):
        return  # Keep northern fields rectangular and strictly under 15 hectares
    if not (cx < m(4) and cy < m(4)):
        return  # Only merge fields near the town to keep canal fields rectangular
    for b in parcels:
        if b is a: continue
        if b[1] < m(1): continue # Avoid merging with northern fields
        # Share vertical edge
        if abs(a[2] - b[0]) < 2:
            y_start = max(a[1], b[1])
            y_end = min(a[3], b[3])
            if y_start < y_end - 10:  # Valid overlap
                x_border = a[2]
                rect(x_border - W_FIELD_BORDER, y_start + 2, x_border + W_FIELD_BORDER, y_end - 2, C_FARM)
                return
        # Share horizontal edge
        if abs(a[3] - b[1]) < 2:
            x_start = max(a[0], b[0])
            x_end = min(a[2], b[2])
            if x_start < x_end - 10:  # Valid overlap
                y_border = a[3]
                rect(x_start + 2, y_border - W_FIELD_BORDER, x_end - 2, y_border + W_FIELD_BORDER, C_FARM)
                return

for _ in range(15):
    draw_L()

# Canals variables
CW = 26
CWB = 16
off = TH_T/2 + CW/2 + GAP



# get_road_x defined at the top of the file

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

road_pts = []
for y_px in range(int(m(1)), int(m(7)) + 1, 4):
    road_pts.append((get_road_x(y_px), y_px))
road_pts.append((m(1), m(7)))

# ================= ROAD WIDTHS AND HELPERS =================
# TH_P, TH_S, TH_T defined at the top of the file

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
    if abs(mid - m(1)) < 1.0:
        return m(1)
    if abs(mid - m(7)) < 1.0:
        return m(7)
    return mid

def draw_hline_segment(x_start, x_end, y, th, col, is_outline=False):
    border = W_ROAD_BORDER if is_outline else 0
    c = C_FARMB if is_outline else col
    rect(x_start, y - th/2 - border, x_end, y + th/2 + border, c)

def draw_vline_segment(x, y_start, y_end, th, col, is_outline=False):
    border = W_ROAD_BORDER if is_outline else 0
    c = C_FARMB if is_outline else col
    rect(x - th/2 - border, y_start - border, x + th/2 + border, y_end + border, c)

# Set up road coordinates
hlines = [m(i) for i in range(MILES+1)]
vlines = [m(i) for i in range(MILES+1)]
sec_v = set()  # No secondary vertical roads

# 1. Draw all road outlines/margins first
for k, y in enumerate(hlines):
    if k == 0 or k == MILES: continue  # No road on the outer borders
    if k == 1 or k == 7: 
        draw_hline_segment(0, S, y, TH_P, None, is_outline=True)
    else: 
        # Track road (cut diagonal forest)
        xc = get_road_x(y)
        x_L = xc - 1300.0
        x_R = xc + 1300.0
        if x_L > 0:
            draw_hline_segment(0, x_L, y, TH_T, None, is_outline=True)
        if x_R < S:
            draw_hline_segment(x_R, S, y, TH_T, None, is_outline=True)

for k, x in enumerate(vlines):
    if k == 0 or k == MILES: continue
    # All vertical roads are track roads, cut around diagonal forest
    y_enter = 1024.0 if (x + 1300.0 > 7168.0) else find_intersection_y(x + 1300.0)
    y_exit = 7168.0 if (x - 1300.0 < 1024.0) else find_intersection_y(x - 1300.0)
    if y_enter > 1024.0:
        draw_vline_segment(x, 1024.0, y_enter, TH_T, None, is_outline=True)
    if y_exit < 7168.0:
        draw_vline_segment(x, y_exit, 7168.0, TH_T, None, is_outline=True)

# Draw diagonal primary road outline
d.line(road_pts, fill=C_FARMB, width=TH_P + 2*W_ROAD_BORDER, joint="round")


# Draw southern track road outlines (cut around southern forest: x in [3782, 4410], y in [7168, 8092])
# south_vertical_track is entirely inside/close to the forest, so it is removed.
# south_horizontal_track is cut 50m from the forest (margin at 3732 and 4460)
d.line([(100, 8040), (3732, 8040)], fill=C_FARMB, width=TH_T + 2*W_ROAD_BORDER, joint="round")
d.line([(4460, 8040), (8092, 8040)], fill=C_FARMB, width=TH_T + 2*W_ROAD_BORDER, joint="round")


# ================= TOWN (1x1 mile Section, rectangular hugging the north-west) =================
# Under the PLSS, a Section is 1x1 mile (640 acres).
# The town occupies column 0..4 (x ∈ [1, 1.625] miles, y ∈ [1, 1.5] miles).
TOWN_X0, TOWN_X1, TOWN_Y0, TOWN_Y1 = m(1), m(2), m(1), m(2)

# Draw rectangular town hugging the north-west
rect(m(1.0), m(1.0), m(1.625), m(1.5), C_RES)

# Draw new farmyards in the 3 easternmost columns (5, 6, 7) of the town section
rect(m(1.625), m(1.0), m(2.0), m(1.5), C_YARD, outline=C_YARDB, width=5)

# PLSS subdivisions: 1 mile = 80 chains.
# Standard town blocks are subdivided into 10 chains x 10 chains (1/8 mile x 1/8 mile = 660 x 660 feet).
# This yields exactly 8x8 blocks, requiring 7 internal streets in each direction.
sw = 3
for i in range(1, 5):
    x = TOWN_X0 + i * (TOWN_X1 - TOWN_X0) / 8
    rect(x-sw/2, TOWN_Y0+m(0.05), x+sw/2, m(1.5), C_RESST)
for i in range(1, 4):
    y = TOWN_Y0 + i * (TOWN_Y1 - TOWN_Y0) / 8
    rect(TOWN_X0+m(0.05), y-sw/2, m(1.625), y+sw/2, C_RESST)

# ================= FORESTS (3 large rectangles, occupying half a section pegged to roads) =================
# C_FOREST fill
# Forest 2: Western half of section [2, 3] x [1, 2], pegged to x=2 (next to town farmyard)
rect(m(2.0), m(1.0), m(2.25), m(2.0), C_FOREST)

# 10 separate sections of the diagonal forest (covering 1000m wide hills) with 50m margins
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
    margin_pts = []
    forest_pts = []
    
    # Margin polygon (y extended by 50m for end margins)
    for y_px in range(int(y0 - 50.0), int(y1 + 50.0) + 1, 4):
        xc = get_road_x(y_px)
        margin_pts.append((min(S - 100.0, xc + 1300.0), y_px))
    for y_px in range(int(y1 + 50.0), int(y0 - 50.0) - 1, -4):
        xc = get_road_x(y_px)
        margin_pts.append((max(100.0, xc - 1300.0), y_px))
        
    # Forest polygon
    for y_px in range(int(y0), int(y1) + 1, 4):
        xc = get_road_x(y_px)
        forest_pts.append((min(S - 100.0, xc + 1250.0), y_px))
    for y_px in range(int(y1), int(y0) - 1, -4):
        xc = get_road_x(y_px)
        forest_pts.append((max(100.0, xc - 1250.0), y_px))
        
    # Draw black margin first
    d.polygon(margin_pts, fill=C_FARMB)
    # Draw forest on top
    d.polygon(forest_pts, fill=C_FOREST)

# Southern forest surrounding the farmyard, reaching both edges (north to south)
rect(3782, 7168, 4410, 8092, C_FOREST)

# ================= FARMYARDS (5 purple squares/rectangles on primary roads) =================
# C_YARD fill, C_YARDB outline
# Each yard is centered on its side of the grid block (section) it hugs.
# Coordinates remove the 5px offset to touch the road fills directly.
yards = [
    # (x0, y0, x1, y1)
    (m(4.375), m(1) + TH_P/2, m(4.625), m(1) + TH_P/2 + m(0.25)),                      # Yard 1: Square (0.25x0.25 mi), centered along y=1, block x ∈ [4, 5]
    (m(2.35), m(7) - TH_P/2 - m(0.3), m(2.65), m(7) - TH_P/2),                         # Yard 2: Square (0.3x0.3 mi), centered along y=7, block x ∈ [2, 3]
    (m(4.4), m(7) - TH_P/2 - m(0.2), m(4.6), m(7) - TH_P/2),                           # Yard 3: Square (0.2x0.2 mi), centered along y=7, block x ∈ [4, 5]
    (m(6.35), m(7) - TH_P/2 - m(0.3), m(6.65), m(7) - TH_P/2),                         # Yard 4: Square (0.3x0.3 mi), centered along y=7, block x ∈ [6, 7]
    (m(1) + TH_P/2, m(4.4), m(1) + TH_P/2 + m(0.2), m(4.6)),                           # Yard 5: Square (0.2x0.2 mi), centered along x=1, block y ∈ [4, 5]
    (m(7) - TH_P/2 - m(0.5), m(4.25), m(7) - TH_P/2, m(4.75)),                           # New Yard: Square (0.5x0.5 mi), centered along x=7 (East primary road), block y ∈ [4, 5]
    (3846, 7380, 4346, 7880)                                                           # Southern Yard: 500x500px in the middle of southern zone
]

for (x0, y0, x1, y1) in yards:
    rect(x0, y0, x1, y1, C_YARD, outline=C_YARDB, width=5)

# ================= INDUSTRIAL (21 grey rectangles: 1 north of town, 20 along primary roads) =================
# Coordinates remove the 5px offset to touch the road fills directly.
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

for (x0, y0, x1, y1) in ind_spots:
    rect(x0, y0, x1, y1, C_IND, outline=C_FARMB, width=3)


# ================= DRAW ROAD FILLS =================
# 2. Draw all road fills on top
for k, y in enumerate(hlines):
    if k == 0 or k == MILES: continue
    if k == 1 or k == 7: 
        draw_hline_segment(0, S, y, TH_P, C_ROADP)
    else: 
        # Track road (cut diagonal forest)
        xc = get_road_x(y)
        x_L = xc - 1255.0
        x_R = xc + 1255.0
        if x_L > 0:
            draw_hline_segment(0, x_L, y, TH_T, C_ROADT)
        if x_R < S:
            draw_hline_segment(x_R, S, y, TH_T, C_ROADT)

for k, x in enumerate(vlines):
    if k == 0 or k == MILES: continue
    # All vertical roads are track roads, cut around diagonal forest
    y_enter = 1024.0 if (x + 1255.0 > 7168.0) else find_intersection_y(x + 1255.0)
    y_exit = 7168.0 if (x - 1255.0 < 1024.0) else find_intersection_y(x - 1255.0)
    if y_enter > 1024.0:
        draw_vline_segment(x, 1024.0, y_enter, TH_T, C_ROADT)
    if y_exit < 7168.0:
        draw_vline_segment(x, y_exit, 7168.0, TH_T, C_ROADT)

# Draw diagonal primary road fill
d.line(road_pts, fill=C_ROADP, width=TH_P, joint="round")


# Draw southern track road fills
# south_vertical_track is removed.
# south_horizontal_track is cut 5m from the forest (margin at 3777 and 4415)
d.line([(100, 8040), (3777, 8040)], fill=C_ROADT, width=TH_T, joint="round")
d.line([(4415, 8040), (8092, 8040)], fill=C_ROADT, width=TH_T, joint="round")


# Paint the 100m border solid black (unassigned area)
rect(0, 0, S, 100, (0, 0, 0))
rect(0, S - 100, S, S, (0, 0, 0))
rect(0, 0, 100, S, (0, 0, 0))
rect(S - 100, 0, S, S, (0, 0, 0))

# Canals, reservoirs, and river removed as per request

img.save("outputs/zoning_map.png")
print("done: map generated with PLSS grid")

