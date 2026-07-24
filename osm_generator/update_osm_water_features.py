#!/usr/bin/env python3
"""
update_osm_water_features.py

Script to add the Reservoir and Canal to the OSM zoning maps (zoning_map manual.osm, zoning_map.osm),
trim the Town Farmyard around the reservoir, and split field/forest polygons around the canal
without producing diagonal or triangular artifacts.
"""

import os
import sys
import math
import xml.etree.ElementTree as ET

def update_osm_file(osm_path):
    print(f"\n--- Processing OSM file: {osm_path} ---")
    if not os.path.exists(osm_path):
        print(f"File not found: {osm_path}, skipping.")
        return

    tree = ET.parse(osm_path)
    root = tree.getroot()

    bounds_elem = root.find("bounds")
    if bounds_elem is None:
        print("Error: <bounds> element not found in OSM file.")
        return

    min_lat = float(bounds_elem.get("minlat"))
    max_lat = float(bounds_elem.get("maxlat"))
    min_lon = float(bounds_elem.get("minlon"))
    max_lon = float(bounds_elem.get("maxlon"))
    S = 8192.0  # Canvas size in meters

    def to_xy(lat, lon):
        x = (lon - min_lon) / (max_lon - min_lon) * S
        y = (max_lat - lat) / (max_lat - min_lat) * S
        return x, y

    def to_gps(x, y):
        lon = min_lon + (x / S) * (max_lon - min_lon)
        lat = max_lat - (y / S) * (max_lat - min_lat)
        return lat, lon

    def get_road_x(y):
        y_miles = y / 1024.0
        if y_miles <= 2.2:
            x_miles = 7.0
        elif y_miles <= 3.8:
            u = (y_miles - 2.2) / 1.6
            x_miles = 4.0 + 3.0 * (1.0 + math.cos(math.pi * u)) / 2.0
        elif y_miles <= 4.2:
            x_miles = 4.0
        elif y_miles <= 5.8:
            u = (y_miles - 4.2) / 1.6
            x_miles = 1.0 + 3.0 * (1.0 + math.cos(math.pi * u)) / 2.0
        else:
            x_miles = 1.0
        return x_miles * 1024.0

    nodes_dict = {}
    for node in root.findall("node"):
        nid = int(node.get("id"))
        lat = float(node.get("lat"))
        lon = float(node.get("lon"))
        x, y = to_xy(lat, lon)
        nodes_dict[nid] = (lat, lon, x, y)

    # Resize Bosque de la Diagonal to 500m total width (250m each side of road center)
    half_width = 250.0
    modified_diag_nodes = set()
    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        if "Bosque de la Diagonal" in tags.get("name", ""):
            nd_refs = [int(nd.get("ref")) for nd in way.findall("nd")]
            for nid in set(nd_refs):
                if nid in modified_diag_nodes or nid not in nodes_dict:
                    continue
                lat, lon, x, y = nodes_dict[nid]
                xc = get_road_x(y)
                if x >= xc:
                    new_x = min(8192.0 - 100.0, xc + half_width)
                else:
                    new_x = max(100.0, xc - half_width)
                new_lat, new_lon = to_gps(new_x, y)
                node_elem = root.find(f"./node[@id='{nid}']")
                if node_elem is not None:
                    node_elem.set("lat", f"{new_lat:.8f}")
                    node_elem.set("lon", f"{new_lon:.8f}")
                    nodes_dict[nid] = (new_lat, new_lon, new_x, y)
                    modified_diag_nodes.add(nid)

    print(f"  Resized {len(modified_diag_nodes)} nodes for Bosque de la Diagonal to 500m total width.")

    # Adjust bordering farmland fields so their edges meet the 500m diagonal forest boundary (255m from road center)
    adjusted_farm_nodes = set()
    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        if tags.get("landuse") == "farmland":
            nd_refs = [int(nd.get("ref")) for nd in way.findall("nd")]
            for nid in set(nd_refs):
                if nid in adjusted_farm_nodes or nid in modified_diag_nodes or nid not in nodes_dict:
                    continue
                lat, lon, x, y = nodes_dict[nid]
                xc = get_road_x(y)
                l_old = xc - 1255.0
                r_old = xc + 1255.0
                l_new = xc - 255.0
                r_new = xc + 255.0

                new_x = None
                if abs(x - l_old) <= 25.0:
                    new_x = l_new
                elif abs(x - r_old) <= 25.0:
                    new_x = r_new

                if new_x is not None:
                    new_lat, new_lon = to_gps(new_x, y)
                    node_elem = root.find(f"./node[@id='{nid}']")
                    if node_elem is not None:
                        node_elem.set("lat", f"{new_lat:.8f}")
                        node_elem.set("lon", f"{new_lon:.8f}")
                        nodes_dict[nid] = (new_lat, new_lon, new_x, y)
                        adjusted_farm_nodes.add(nid)

    print(f"  Adjusted {len(adjusted_farm_nodes)} farmland border nodes to fit the 500m diagonal forest boundary.")

    max_node_id = max(int(n.get("id")) for n in root.findall("node"))
    max_way_id = max(int(w.get("id")) for w in root.findall("way"))

    def create_node(x, y):
        nonlocal max_node_id
        max_node_id += 1
        lat, lon = to_gps(x, y)
        node_elem = ET.Element("node", {
            "id": str(max_node_id),
            "lat": f"{lat:.8f}",
            "lon": f"{lon:.8f}",
            "version": "1",
            "changeset": "1",
            "user": "osm_generator",
            "uid": "1",
            "timestamp": "2026-07-24T00:00:00Z"
        })
        nodes_dict[max_node_id] = (lat, lon, x, y)
        return max_node_id, node_elem

    new_nodes_to_insert = []
    new_ways_to_append = []

    # 1. Add natural=water polygon (Reservoir + Canal) if not present
    has_water_polygon = False
    for way in root.findall("way"):
        for tag in way.findall("tag"):
            if tag.get("k") == "name" and tag.get("v") == "Embalse y Canal de la Granja":
                has_water_polygon = True
                break

    if not has_water_polygon:
        polygon_pts = [
            (1664.0, 1536.0), # SW Reservoir
            (1664.0, 1280.0), # NW Reservoir
            (2048.0, 1280.0), # NE Reservoir
            (2048.0, 1403.0), # Junction North Reservoir-Canal
            (4096.0, 1403.0), # Canal North Mid 1
            (6144.0, 1403.0), # Canal North Mid 2
            (8192.0, 1403.0), # NE Canal (East Map Edge)
            (8192.0, 1413.0), # SE Canal (East Map Edge)
            (6144.0, 1413.0), # Canal South Mid 2
            (4096.0, 1413.0), # Canal South Mid 1
            (2048.0, 1413.0), # Junction South Reservoir-Canal
            (2048.0, 1536.0), # SE Reservoir
            (1664.0, 1536.0), # Close back to SW Reservoir
        ]

        water_node_ids = []
        for idx, (x, y) in enumerate(polygon_pts):
            if idx == len(polygon_pts) - 1:
                water_node_ids.append(water_node_ids[0])
                continue
            nid, nelem = create_node(x, y)
            new_nodes_to_insert.append(nelem)
            water_node_ids.append(nid)

        max_way_id += 1
        water_way = ET.Element("way", {
            "id": str(max_way_id),
            "version": "1",
            "changeset": "1",
            "user": "osm_generator",
            "uid": "1",
            "timestamp": "2026-07-24T00:00:00Z"
        })

        for nid in water_node_ids:
            ET.SubElement(water_way, "nd", {"ref": str(nid)})

        ET.SubElement(water_way, "tag", {"k": "natural", "v": "water"})
        ET.SubElement(water_way, "tag", {"k": "water", "v": "reservoir"})
        ET.SubElement(water_way, "tag", {"k": "name", "v": "Embalse y Canal de la Granja"})

        new_ways_to_append.append(water_way)
        print(f"  Created natural=water polygon (Way ID {max_way_id})")

    # 2. Trim Town Farmyard and split fields/forests crossing canal (with 10m buffer gap from canal edges)
    y_canal_north = 1393.0 # 10m north of canal edge (1403.0 - 10.0)
    y_canal_south = 1423.0 # 10m south of canal edge (1413.0 + 10.0)
    y_res_north = 1280.0

    for way in root.findall("way"):
        wid = int(way.get("id"))
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        landuse = tags.get("landuse")
        natural = tags.get("natural")
        if landuse not in ["farmland", "farmyard", "forest"] and natural not in ["wood"]:
            continue

        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        nd_refs = [int(nd.get("ref")) for nd in way.findall("nd")]
        pts = [nodes_dict[r] for r in nd_refs if r in nodes_dict]

        if not pts:
            continue

        min_y = min(p[3] for p in pts)
        max_y = max(p[3] for p in pts)
        min_x = min(p[2] for p in pts)
        max_x = max(p[2] for p in pts)

        # Trim Town Farmyard (Way 189)
        if wid == 189 or (tags.get("landuse") == "farmyard" and min_x >= 1600 and max_x <= 2100 and min_y >= 1000 and max_y <= 1600 and "natural" not in tags):
            if max_y > y_res_north:
                print(f"  Trimming Town Farmyard Way {wid} to y <= {y_res_north:.1f}")
                n1_id, n1_elem = create_node(min_x, min_y)
                n2_id, n2_elem = create_node(max_x, min_y)
                n3_id, n3_elem = create_node(max_x, y_res_north)
                n4_id, n4_elem = create_node(min_x, y_res_north)

                new_nodes_to_insert.extend([n1_elem, n2_elem, n3_elem, n4_elem])

                for child in list(way):
                    if child.tag == "nd":
                        way.remove(child)

                tag_idx = 0
                for idx, child in enumerate(list(way)):
                    if child.tag == "tag":
                        tag_idx = idx
                        break

                for nid in [n1_id, n2_id, n3_id, n4_id, n1_id]:
                    nd_elem = ET.Element("nd", {"ref": str(nid)})
                    way.insert(tag_idx, nd_elem)
                    tag_idx += 1
            continue

        # Split Field/Forest polygons across canal (y=1403 to y=1413)
        if min_y < y_canal_north and max_y > y_canal_south:
            print(f"  Splitting Way {wid} ({tags.get('name', tags.get('landuse', tags.get('natural')))}) X=[{min_x:.1f},{max_x:.1f}] across canal")

            # Collect existing intermediate nodes along left wall (x ~ min_x), right wall (x ~ max_x), bottom wall (y ~ max_y)
            left_pts = [p for p in pts if abs(p[2] - min_x) < 5.0]
            right_pts = [p for p in pts if abs(p[2] - max_x) < 5.0]
            bot_pts = [p for p in pts if abs(p[3] - max_y) < 5.0]

            # --- NORTH PIECE (y: min_y -> 1403.0) ---
            n_cut_left_id, n_cut_left_elem = create_node(min_x, y_canal_north)
            n_cut_right_id, n_cut_right_elem = create_node(max_x, y_canal_north)

            # Corner nodes
            n_top_left_id, n_top_left_elem = create_node(min_x, min_y)
            n_top_right_id, n_top_right_elem = create_node(max_x, min_y)

            new_nodes_to_insert.extend([n_cut_left_elem, n_cut_right_elem, n_top_left_elem, n_top_right_elem])

            # Right wall nodes for North piece (sorted by y increasing, strictly between min_y and 1403)
            n_right_nodes = sorted([p for p in right_pts if min_y < p[3] < y_canal_north], key=lambda p: p[3])

            # Left wall nodes for North piece (sorted by y decreasing, strictly between 1403 and min_y)
            n_left_nodes = sorted([p for p in left_pts if min_y < p[3] < y_canal_north], key=lambda p: p[3], reverse=True)

            north_sequence = [n_top_left_id, n_top_right_id]
            for p in n_right_nodes:
                pid = [r for r in nd_refs if nodes_dict[r] == p][0]
                north_sequence.append(pid)

            north_sequence.append(n_cut_right_id)
            north_sequence.append(n_cut_left_id)

            for p in n_left_nodes:
                pid = [r for r in nd_refs if nodes_dict[r] == p][0]
                north_sequence.append(pid)

            north_sequence.append(n_top_left_id) # Close ring

            # Update existing way element with North ring
            for child in list(way):
                if child.tag == "nd":
                    way.remove(child)

            tag_idx = 0
            for idx, child in enumerate(list(way)):
                if child.tag == "tag":
                    tag_idx = idx
                    break

            for nid in north_sequence:
                way.insert(tag_idx, ET.Element("nd", {"ref": str(nid)}))
                tag_idx += 1

            # --- SOUTH PIECE (y: 1413.0 -> max_y) ---
            s_cut_left_id, s_cut_left_elem = create_node(min_x, y_canal_south)
            s_cut_right_id, s_cut_right_elem = create_node(max_x, y_canal_south)
            s_bot_right_id, s_bot_right_elem = create_node(max_x, max_y)
            s_bot_left_id, s_bot_left_elem = create_node(min_x, max_y)

            new_nodes_to_insert.extend([s_cut_left_elem, s_cut_right_elem, s_bot_right_elem, s_bot_left_elem])

            # Right wall nodes for South piece (sorted by y increasing, strictly between 1413 and max_y)
            s_right_nodes = sorted([p for p in right_pts if y_canal_south < p[3] < max_y], key=lambda p: p[3])

            # Bottom wall nodes for South piece (sorted by x decreasing, strictly between max_x and min_x)
            s_bot_nodes = sorted([p for p in bot_pts if min_x < p[2] < max_x], key=lambda p: p[2], reverse=True)

            # Left wall nodes for South piece (sorted by y decreasing, strictly between max_y and 1413)
            s_left_nodes = sorted([p for p in left_pts if y_canal_south < p[3] < max_y], key=lambda p: p[3], reverse=True)

            south_sequence = [s_cut_left_id, s_cut_right_id]

            for p in s_right_nodes:
                pid = [r for r in nd_refs if nodes_dict[r] == p][0]
                south_sequence.append(pid)

            south_sequence.append(s_bot_right_id)

            for p in s_bot_nodes:
                pid = [r for r in nd_refs if nodes_dict[r] == p][0]
                south_sequence.append(pid)

            south_sequence.append(s_bot_left_id)

            for p in s_left_nodes:
                pid = [r for r in nd_refs if nodes_dict[r] == p][0]
                south_sequence.append(pid)

            south_sequence.append(s_cut_left_id) # Close ring

            # Create new way element for South piece
            max_way_id += 1
            south_way = ET.Element("way", {
                "id": str(max_way_id),
                "version": "1",
                "changeset": "1",
                "user": "osm_generator",
                "uid": "1",
                "timestamp": "2026-07-24T00:00:00Z"
            })

            for nid in south_sequence:
                ET.SubElement(south_way, "nd", {"ref": str(nid)})

            for k, v in tags.items():
                ET.SubElement(south_way, "tag", {"k": k, "v": v})

            new_ways_to_append.append(south_way)

    # Insert new nodes before first way
    first_way_idx = None
    for i, elem in enumerate(root):
        if elem.tag == "way":
            first_way_idx = i
            break

    if first_way_idx is not None:
        for node_elem in reversed(new_nodes_to_insert):
            root.insert(first_way_idx, node_elem)
    else:
        for node_elem in new_nodes_to_insert:
            root.append(node_elem)

    for way_elem in new_ways_to_append:
        root.append(way_elem)

    def indent(elem, level=0):
        i = "\n" + level*"  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "  "
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
            for subelem in elem:
                indent(subelem, level+1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    indent(root)
    tree.write(osm_path, encoding="utf-8", xml_declaration=True)
    print(f"Successfully updated {osm_path}!")

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    outputs_dir = os.path.join(script_dir, "outputs")

    osm_files = [
        os.path.join(outputs_dir, "zoning_map manual.osm"),
        os.path.join(outputs_dir, "zoning_map.osm")
    ]

    for osm_path in osm_files:
        update_osm_file(osm_path)

    # Render updated zoning_map.png
    try:
        from render_osm_to_png import render_osm
        target_osm = os.path.join(outputs_dir, "zoning_map manual.osm")
        if not os.path.exists(target_osm):
            target_osm = os.path.join(outputs_dir, "zoning_map.osm")
        output_png = os.path.join(outputs_dir, "zoning_map.png")
        render_osm(target_osm, output_png)
    except Exception as e:
        print(f"Warning: Failed to render PNG: {e}")

if __name__ == "__main__":
    main()
