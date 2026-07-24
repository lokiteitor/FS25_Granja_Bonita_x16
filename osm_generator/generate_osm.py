#!/usr/bin/env python3
import os
import math
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import numpy as np
from PIL import Image
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
    # We include X = 7103.0 as a node to connect the new primary road.
    xs_sec = [7118.0, 7278.0, 7438.0, 7598.0, 7758.0]
    xs_primary_all = sorted([7103.0] + xs_sec)
    primary_coords = [(0.0, 1009.0)] + [(x, 1009.0) for x in xs_primary_all] + [(8192.0, 1009.0)]
    add_way(primary_coords, {'highway': 'primary', 'name': 'Primary Road'})

    # 7b. New Southern-to-Western Primary Road
    # - Horizontal from (0, 7650) to (5068, 7650)
    # - Curve 1 (Bezier) to (5580.13, 7437.87)
    # - Diagonal to (6890.87, 6127.13)
    # - Curve 2 (Bezier) to (7103, 5615)
    # - Vertical to (7103, 1009)
    def bezier_curve(p0, p1, p2, num_pts=10):
        pts = []
        for i in range(num_pts):
            t = i / (num_pts - 1)
            x = (1-t)**2 * p0[0] + 2*(1-t)*t * p1[0] + t**2 * p2[0]
            y = (1-t)**2 * p0[1] + 2*(1-t)*t * p1[1] + t**2 * p2[1]
            pts.append((x, y))
        return pts

    new_primary_coords = []
    # Segment 1: West edge to start of Curve 1
    new_primary_coords.append((0.0, 7650.0))
    new_primary_coords.append((5068.0, 7650.0))
    
    # Curve 1
    c1_pts = bezier_curve((5068.0, 7650.0), (5368.0, 7650.0), (5580.13, 7437.87))
    new_primary_coords.extend(c1_pts[1:-1])
    
    # Segment 2: end of Curve 1 to start of Curve 2
    new_primary_coords.append((5580.13, 7437.87))
    new_primary_coords.append((6890.87, 6127.13))
    
    # Curve 2
    c2_pts = bezier_curve((6890.87, 6127.13), (7103.0, 5915.0), (7103.0, 5615.0))
    new_primary_coords.extend(c2_pts[1:-1])
    
    # Segment 3: end of Curve 2 to connection with northern primary road
    new_primary_coords.append((7103.0, 5615.0))
    new_primary_coords.append((7103.0, 1536.0)) # Intersection with horiz secondary 3
    new_primary_coords.append((7103.0, 1280.0)) # Intersection with horiz secondary 2
    new_primary_coords.append((7103.0, 1024.0)) # Intersection with horiz secondary 1
    new_primary_coords.append((7103.0, 1009.0)) # Intersection with northern primary road
    
    add_way(new_primary_coords, {'highway': 'primary', 'name': 'Southern Link Road'})

    # 8. Railway
    # Passing 15m north of Primary Road (Y: 1009 - 15 = 994)
    # Parallel to Primary Road
    rail_coords = [(0.0, 994.0), (8192.0, 994.0)]
    add_way(rail_coords, {'railway': 'rail', 'name': 'Railway'})

    # 9. Secondary Roads (Grid in Town)
    # Vertical secondary roads from Y: 1009 (connecting to Primary) down to Y: 1536
    # Intersection points with horizontal roads are at Y: 1024, 1280, 1536
    ys_sec_v = [1009.0, 1024.0, 1280.0, 1536.0]
    for x in xs_sec:
        v_coords = [(x, y) for y in ys_sec_v]
        add_way(v_coords, {'highway': 'secondary'})

    # Horizontal secondary roads inside the Town at Y: 1024, 1280, 1536
    # Extended to X = 7103.0 to connect to the new primary road
    xs_sec_h = [7103.0] + xs_sec
    ys_sec_h = [1024.0, 1280.0, 1536.0]
    for y in ys_sec_h:
        h_coords = [(x, y) for x in xs_sec_h]
        add_way(h_coords, {'highway': 'secondary'})

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
        Image.MAX_IMAGE_PIXELS = None
        script_dir = os.path.dirname(os.path.abspath(__file__))
        dem_path = os.path.normpath(os.path.join(script_dir, "../dem_generator/dem_new_12k.png"))
        
        if not os.path.exists(dem_path):
            print(f"Error: DEM file not found at {dem_path}")
            return []
            
        img = Image.open(dem_path)
        data = np.array(img, dtype=np.float32)
        playable = data[2048:10240, 2048:10240]
        
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
        add_way(poly, {
            'natural': 'wood',
            'landuse': 'farmyard',
            'leaf_type': 'needleleave'
        })
        print(f"   Added forest way {i+1} with {len(poly)} nodes.")

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
    # Sort nodes by id
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
