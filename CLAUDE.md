# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A generator for a Farming Simulator 25 map ("Granja Bonita"). It produces two artefacts a
human then imports into Giants Editor: a 16-bit heightmap PNG (`dem_generator/dem_new_12k.png`)
and an OSM vector file (`osm_generator/map.osm`). There is no application and no test
suite. Verification is two acceptance scripts that exit non-zero, plus `map_layout.validate()`,
which both generators run first and refuse to proceed on.

The user works in Spanish (commit messages, `pf_generator/README.md`, `render_pda.py`);
code and most docstrings are in English. Either language is fine in replies.

## Commands

    python3 map_layout.py                             # layout self-check, ~3 s, no output files
    python3 dem_generator/generate_new_dem_12k.py     # ~4 min -> dem_new_12k.png, terrain_stats.json, 2 preview PNGs
    python3 dem_generator/measure_elevation.py        # acceptance report on the DEM, exit 1 on failure
    python3 osm_generator/generate_osm.py             # -> map.osm
    python3 osm_generator/check_osm.py                # inventory + invariants, exit 1 on failure
    python3 osm_generator/visualize_osm.py            # -> map_osm_visual.png (2D render)
    python3 visualizer/create_3d_viewer.py            # -> dem_viewer_3d.html (Three.js, DEM + OSM together)

Run the DEM before the OSM: `generate_osm.py` reads `dem_generator/terrain_stats.json`,
which the DEM publishes. Scripts work from the repo root or their own directory; each
puts what it needs on `sys.path`. System `python3` (3.14) has numpy, scipy, Pillow and
matplotlib. There is no `.venv` despite what older READMEs say.

Independent of the pipeline:

    python3 pf_generator/generate_soil.py -s <seed>   # Precision Farming soilMap.png, pure seeded noise
    python3 render_pda.py                             # Windows-only: paints overview.dds for the mod folder via texconv.exe, hard-coded paths

## Architecture

**`map_layout.py` is the single source of geometry.** The DEM sculpts around it and the
OSM writes it out; neither half may define geometry of its own. A feature in one output
and not the other is invisible in either on its own. Standard library only: nothing in
`osm_generator/` may import numpy, and terrain facts the OSM side needs come through
`terrain_stats.json` via `map_layout.load_roughness()`, never re-derived.

**The geometry comes from `input/custom_osm.osm`, not from code.** The loader block at
the bottom of `map_layout.py` (look for `_INPUT_OSM`) parses that JOSM file at import time
and fills the registries:

| Registry | Filled from | What it is |
|---|---|---|
| `CORRIDORS` | `highway=*` ways | roads: axis, class, platform half-width, feather, grade |
| `WATER` | `natural=water` | the one lake, as a shore ring |
| `PADS` | `landuse=farmyard`, `place=town` | levelled platforms (terrain only; `m4fs:level=yes` marks which yards get graded) |
| `AREAS` | woods, fields, farmyards | every tagged ring the OSM draws; `FIELDS` is the farmland subset |
| `SHELTERBELTS` | **derived** by `build_shelterbelts(FIELDS)` | the only feature computed rather than read; fields are cut back to make room |

Ways are dropped by id in two sets (`_TOWN_RESERVOIR_WAYS`, `_DROPPED_WAYS`) so the input
file stays the untouched survey and the module stays the record of what is built. The
wood on way `EAST_RIDGE_WAY` is stretched out to the clean strip because the DEM runs
that ridge into the border.

**Much of `map_layout.py` is dead code from the previous procedural map.** The river,
PLSS road grid, towns, roadside yards, gallery timber and aliquot parcelling (roughly
lines 160 to 2600: `river_axis`, `_ns_road`, `town_*`, `roadside_pad`, `gallery_areas`,
`build_fields`, and their `RIVER_*`/`PLSS_*`/`TOWN_*`/`FIELD_*`/`GALLERY_*` constants) still
compile and some constants are still referenced (`TOWN_PAD_FEATHER_M`, `YARD_FEATHER_M`,
`FIELD_MIN_HA`, `FIELD_CORNER_R_M`, the `SHELTER_*` block), but none of that geometry
reaches the output. The module docstring and many comments still describe the old map.
Trust `python3 map_layout.py` and the loader block over any prose.

**The DEM generator discards its own synthesis.** `generate_new_dem_12k.py` runs the whole
documented pipeline (`build_base`, `sculpt`, `build_rim`, `write_dem`) and then, in `main()`,
if `input/valle_bonito.png` exists it replaces the result with that file: the non-playable
border is copied verbatim (after `fill_border_trenches`), and the playable square is that
file's playable square passed through `clean_town_and_reservoir_area`, `level_platforms`
(the one place `PADS` actually reach the ground), `sculpt_western_lake` and
`extend_east_ridge`, then blended into the border over a 100 m apron. So the `RIM_*`
constants, `build_rim`, `grade_pads` and `grade_corridors` do not affect the output, and a
border defect has to be measured in the source PNG and fixed after the copy in `main()`.
The module carries two definitions each of `rim_crest` and `rim_ramp`; the later pair wins.

**The acceptance harness.** `measure_elevation.py` checks canvas size, encoding, elevation
bands, slope, and that `terrain_stats.json` matches the PNG. `check_osm.py` checks node
and ring integrity, the closed tag vocabulary, the clean strip, and that the file and
the layout agree. Both call `validate()`. When adding a placement rule, add it to
`validate()` rather than only fixing coordinates.

Support modules: `osm_generator/map_extent.py` and `map_source.py` are re-export shims so
the OSM scripts and the 3D viewer read the projection from `map_layout`. `dem_generator/terrain_ops.py`
holds the terrain primitives (`soft_min`, `limit_grade`, `limit_slope`, `rect_sdf`, `rim_field`).

`FS25_Granja_bonita/` is the Maps4FS-generated mod folder. Nothing in this pipeline
writes into it; getting the DEM and OSM in there is a manual Giants Editor step.

## Coordinates and encoding

- Playable metres: **x east, y south from the north edge**, centre `(4096, 4096)`. Canvas
  is 12288 m with the 8192 m playable square centred, so canvas coordinates run
  `-2048 .. 10240` in the same frame.
- Projection is equirectangular about `LAT_CENTER, LON_CENTER` at 111111.0 m per degree.
  The loader derives its own centre from the input file's `<bounds>`; the module constants
  match it. Moving either moves every node in `map.osm` relative to the heightmap and
  nothing downstream catches it.
- Heights are 16-bit centimetres: raw 4640 = 46.40 m. `BASE_ELEV_M` (46.4) is a datum, not
  a height anything sits at.
- The DEM synthesis grid is 3072 px (4 m/px); the output is 12288 px (1 m/px). Working pixel
  `j` is at canvas metre `4j + 2`, output pixel `i` at `i + 0.5`. `level_platforms` works
  directly at 1 m/px in playable metres with pixel centres at `i + 0.5`.
- A 50 m clean strip (`EDGE_CLEAR_M`) inside the playable boundary: every ring the OSM
  draws is clipped back to it (`strip_ring`), pads are held inside it by extent, and
  `check_osm.py` fails on anything planted in it. Roads and water are exempt.

## OSM tag vocabulary is closed

Emit only what `map_layout.RENDERED_TAGS` lists: `natural=water` (+ `water=*`),
`natural=wood`, `landuse=forest|farmyard|farmland`, `highway=*`, `railway=*`. Both
renderers (`visualize_osm.py`, `create_3d_viewer.py`) silently drop anything else, and
`check_osm.py` fails the build over a way whose only tags are outside the list.
Attribute tags on a drawable ring (`leaf_type`, `building`) are fine. Every wood ring
carries both `natural=wood` and `landuse=farmyard` (`wood_tags()`); all three renderers
test wood first, so that is safe. Rings must close on the same node id or the 3D viewer
draws them as lines.

## Pitfalls that still apply

The full list of bugs found on the previous map is in the old CLAUDE.md at commit
`4926122` ("Things that have already gone wrong here"). The ones the current code can hit:

- **Clip a ring, do not clamp it.** Clamping folds overhanging vertices onto the boundary.
  `clip_ring_to_rect` / `strip_ring` only ever put a vertex on the ring's own edge.
- **Offsetting a polyline** by more than its radius of curvature folds the ring through
  itself (`offset_polyline`). Shelterbelt and buffer code must respect this.
- **A vertex-in-polygon test misses two rectangles crossing in a plus.** Use
  `rings_overlap`, which tests edges too.
- **Platform feathers must widen with the cut**: `max(nominal, 1.5*|dz|/tan(4 deg))`,
  capped at `FEATHER_CAP_M`. `level_platforms` does this; keep it when touching pads.
- **Arrive at flat ground with `smootherstep`, not `smoothstep`**, where the surface
  meets a datum, or the 4 m to 1 m resample rings on the curvature jump.
- **Measure the thing, not its average.** Slope is read over a 5 m baseline because the
  centimetre quantisation gives a ~0.3 degree noise floor per pixel.
- **Determinism**: no floating-point randomness in alignments; the DEM uses named RNG
  streams with fixed indices (`STREAMS`) and seed `map_layout.SEED`.
