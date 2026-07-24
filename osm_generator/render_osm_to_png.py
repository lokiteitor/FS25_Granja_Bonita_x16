#!/usr/bin/env python3
"""
render_osm_to_png.py

Renders zoning_map manual.osm to an 8192x8192 PNG image (outputs/zoning_map.png)
showing fields, forests, farmyards, reservoir/canal water, and roads.
"""

import os
import sys
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw

def render_osm(osm_path, output_png_path, canvas_size=8192):
    print(f"Loading OSM from: {osm_path}...")
    if not os.path.exists(osm_path):
        print(f"Error: {osm_path} does not exist.")
        return

    tree = ET.parse(osm_path)
    root = tree.getroot()

    bounds_elem = root.find("bounds")
    min_lat = float(bounds_elem.get("minlat"))
    max_lat = float(bounds_elem.get("maxlat"))
    min_lon = float(bounds_elem.get("minlon"))
    max_lon = float(bounds_elem.get("maxlon"))
    S = float(canvas_size)

    def to_xy(lat, lon):
        x = (lon - min_lon) / (max_lon - min_lon) * S
        y = (max_lat - lat) / (max_lat - min_lat) * S
        return (x, y)

    nodes = {}
    for node in root.findall("node"):
        nid = int(node.get("id"))
        lat = float(node.get("lat"))
        lon = float(node.get("lon"))
        nodes[nid] = to_xy(lat, lon)

    img = Image.new("RGB", (canvas_size, canvas_size), color=(18, 18, 18))
    draw = ImageDraw.Draw(img)

    ways_farmland = []
    ways_farmyard = []
    ways_wood = []
    ways_water = []
    ways_track = []
    ways_primary = []
    ways_railway = []

    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        refs = [int(nd.get("ref")) for nd in way.findall("nd")]
        pts = [nodes[r] for r in refs if r in nodes]

        if not pts:
            continue

        if tags.get("railway") == "rail":
            ways_railway.append((pts, tags))
        elif tags.get("natural") == "water" or tags.get("water") == "reservoir":
            ways_water.append((pts, tags))
        elif tags.get("natural") == "wood" or tags.get("landuse") == "forest":
            ways_wood.append((pts, tags))
        elif tags.get("landuse") == "farmyard":
            ways_farmyard.append((pts, tags))
        elif tags.get("landuse") == "farmland":
            ways_farmland.append((pts, tags))
        elif tags.get("highway") == "primary":
            ways_primary.append((pts, tags))
        elif "highway" in tags:
            ways_track.append((pts, tags))

    # Render Farmland
    for pts, tags in ways_farmland:
        draw.polygon(pts, fill=(43, 58, 40), outline=(92, 122, 75), width=3)

    # Render Farmyards
    for pts, tags in ways_farmyard:
        draw.polygon(pts, fill=(61, 53, 43), outline=(140, 123, 108), width=3)

    # Render Forests / Wood
    for pts, tags in ways_wood:
        draw.polygon(pts, fill=(14, 46, 26), outline=(46, 111, 71), width=3)

    # Render Water (Reservoir & Canal)
    for pts, tags in ways_water:
        draw.polygon(pts, fill=(21, 101, 192), outline=(13, 71, 161), width=4)

    # Render Railway Tracks
    for pts, tags in ways_railway:
        draw.line(pts, fill=(50, 50, 50), width=10, joint="round")
        draw.line(pts, fill=(220, 220, 220), width=4, joint="round")

    # Render Track Roads
    for pts, tags in ways_track:
        draw.line(pts, fill=(176, 137, 104), width=8, joint="round")

    # Render Primary Roads
    for pts, tags in ways_primary:
        draw.line(pts, fill=(191, 54, 12), width=18, joint="round")
        draw.line(pts, fill=(230, 81, 0), width=12, joint="round")

    # Render 100m map border
    draw.rectangle([0, 0, canvas_size, 100], fill=(0, 0, 0))
    draw.rectangle([0, canvas_size - 100, canvas_size, canvas_size], fill=(0, 0, 0))
    draw.rectangle([0, 0, 100, canvas_size], fill=(0, 0, 0))
    draw.rectangle([canvas_size - 100, 0, canvas_size, canvas_size], fill=(0, 0, 0))

    print(f"Saving rendered zoning map PNG to: {output_png_path}...")
    img.save(output_png_path)
    print("Successfully saved zoning_map.png!")

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    osm_path = os.path.join(script_dir, "outputs", "zoning_map manual.osm")
    if not os.path.exists(osm_path):
        osm_path = os.path.join(script_dir, "outputs", "zoning_map.osm")

    output_png_path = os.path.join(script_dir, "outputs", "zoning_map.png")
    render_osm(osm_path, output_png_path)

if __name__ == "__main__":
    main()
