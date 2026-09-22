#!/usr/bin/env python3
"""FS25 heightmap generator.

Builds the 12288x12288 m canvas (1 px = 1 m) with the 8192x8192 m playable area centred
in it. The playable square is a till plain whose mean is `map_layout.BASE_ELEV_M`, with a
river and a lake cut into it in a valley of their own, the Public Land Survey road grid
graded across it, and four towns levelled onto it where a trunk road meets a bridged
section line. The 2048 m border around it is the wall of the valley the map sits in. Two mountain ranges stand in the east and west
border and climb from the valley floor at 20 m to summits at `RIM_CREST_M`, 250 m, with
saddles between them at `RIM_SADDLE_M`; north and south the valley runs on out of the map
over a sill at `RIM_MOUTH_M`, so the horizon closes on two sides and opens on two.

The rim is built the way the rim always has to be built here: **last, and by addition**.
Anything already in the border rides up the flank intact under `z + h`, where a second
surface blended in would smear it out; and the ramp is a smoothstep of the *4-norm* of
the distance outside the playable square, because a plain maximum creases along the
diagonals and puts four seams out of the corners. It is also entirely and exactly zero
inside the playable boundary and across the `RIM_APRON_M` of apron beyond it, which is
what lets the playable square still measure flat to the centimetre with the flank of a
250 m range starting 100 m outside it.

Everything the terrain would be shaped around - where the water runs, where the roads
are, where the yards sit - comes from `map_layout.py` at the root of the tree, which the
OSM generator reads too. Neither half invents its own geometry: the rim's constants live
there and its one implementation is `terrain_ops.rim_field`, which the acceptance script
reads back to find the strips it reports on. A feature added to the registries without a
sculpting stage here is the exact failure the shared-geometry rule exists to prevent -
the vectors would draw a river the ground knows nothing about - so `sculpt()` carries the
whole build order in its docstring and the acceptance script checks that every platform
in the layout is both carved and drawn. The rim needs no vectors of its own because none
of it is ground the player can reach.

Heights are stored as 16-bit centimetres (raw / 100 = metres), matching the rest of the
project and Giants Editor's import convention. 20 m is raw 2000.

Two pieces of the machinery are worth knowing about before reading the code, because
they are what the sculpting stages will be built back on top of:

* The relief is synthesised at 3072x3072 (4 m per pixel) and resampled once to the full
  canvas. At full resolution a single Gaussian blur costs 7.2 s and one distance
  transform costs 12.7 s and 5.6 GB; a real terrain pipeline needs about twenty of them.
  Nothing in the terrain may have a wavelength under ~110 m, which is an order of
  magnitude above the Nyquist limit of the working grid, so the resampling loses nothing.
* The canvas metre of working pixel `j` is `4j + 2`, and the centre of output pixel `i`
  is `i + 0.5`. Getting that wrong shifts the terrain against the vectors by metres and
  is invisible in the image.

The primitives the sculpting is written with - `soft_min`, `limit_grade`, `limit_slope`,
`polyline_field`, the envelopes - are all still in `terrain_ops.py`, untouched.
"""
import json
import math
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw
Image.MAX_IMAGE_PIXELS = None

from scipy import ndimage

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import map_layout as ml                                             # noqa: E402
import terrain_ops as ops                                           # noqa: E402

# --- canvas geometry -------------------------------------------------------------------
CANVAS_M = int(ml.CANVAS_M)
PLAYABLE_M = int(ml.PLAYABLE_M)
OFFSET_M = int(ml.OFFSET_M)

WORK_PX = 3072
WORK_DX = CANVAS_M / WORK_PX          # 4 m per working pixel
BAND_ROWS = 1024                      # output is written in twelve of these

# --- datum -----------------------------------------------------------------------------
BASE_ELEV_M = ml.BASE_ELEV_M          # the height of the blank sheet, from the layout
Z_MAX_CM = 62000.0                    # Giants' working ceiling, in centimetres

# --- surface finish --------------------------------------------------------------------
# Both off while the map is a base plane: the brief is BASE_ELEV_M everywhere, exactly,
# and 4 cm of micro-relief plus a centimetre of dither would make it BASE_ELEV_M +- 5 cm
# and put a texture in the file that nothing asked for. They are kept here rather than
# deleted because they are the last two stages of any real terrain and both have to come
# back with it: the micro-relief has to stay off running surfaces and channels (4 cm over
# the 25 m the ruling grade is measured across is 8 cm of slope, a quarter of the
# railway's whole budget), and the dither decorrelates the rounding error from the
# surface so a flat yard shows grain instead of contour banding.
MICRO_AMP_M = 0.0                     # surface texture, added at full resolution
MICRO_LAM_M = 14.0
DITHER_CM = 0.0

# How softly the water's cross-section meets the ground it is cut into. The section
# already arrives at the floodplain with zero gradient, so this only has to round the
# corner where the river's valley and the lake's overlap; a large k here would eat the
# valley rim itself.
WATER_BLEND_M = 1.5

# The widest a road platform's feather is allowed to grow. It is sized at
# 1.5*|dz|/tan(4 deg), which is right and which runs away where a road crosses ground it
# disagrees with by a lot: against a riverbed five metres under the floodplain it once
# reached 170 m, and six roads filled the channel to within a metre of its lip. The water
# is taken out of `dz` first; this is the belt to that pair of braces.
FEATHER_CAP_M = 120.0

MASTER_SEED = ml.SEED
# Named streams with fixed, spaced indices: adding one later must not shift the streams
# that already exist, or the whole terrain changes underneath you.
STREAMS = {'moraine': 20, 'swell': 21, 'swale': 22, 'warp_x': 23, 'warp_y': 24,
           'rim_spur': 10, 'rim_rough': 11, 'micro': 40, 'dither': 41,
           'till_swell': 30, 'till_swale': 31, 'till_knob': 32,
           'till_warp_x': 33, 'till_warp_y': 34}

STATS_GRID = 128                      # terrain_stats.json resolution
# What counts as fully broken ground, as a gradient. The parcelling reads this to size
# fields, so it has to discriminate across the ground the map actually has: at the 3%
# it was set to while the map was a flat plate, the till plain's own swells saturate it
# and every cell on the map reads 1.000, which tells the parcelling nothing at all. Six
# degrees puts the flats near zero, the moraine flanks in the middle and the valley
# sides at the top.
ROUGH_FULL_SCALE = 0.105              # tan(6 deg)


def rng_for(name):
    return np.random.default_rng([MASTER_SEED, STREAMS[name]])


# ==================================================================================
# the surface
# ==================================================================================
def build_base(X, Y):
    """Stage 1: the till plain, after the country round Royal in Clay County, Iowa.

    Three octaves and a warp. They are not a generic fbm with a fixed lacunarity - each
    is a different thing on the ground and they are sized and shaped separately:

    * the **moraines** are stretched `LAND_MORAINE_STRETCH` times along a northwest-
      southeast grain, because a recessional moraine is a line the ice edge stopped on
      and not a blob. Isotropic noise at this wavelength reads as hills, which is the
      one thing this landscape does not have.
    * the **swell and swale** is the till surface itself, aimless and a couple of metres.
    * the **swale** octave under it keeps the ground from looking rolled.
    * the **warp** displaces the whole lot by up to `LAND_WARP_M` at long wavelength, so
      no ridge line reads as the sine it is underneath.

    The real place has prairie potholes over all of this, and they are deliberately left
    out: closed depressions a metre or two deep read as craters at any vertical
    exaggeration that makes the rest of the relief visible.

    Called by the measurer too. It has to be: "where is the upland" needs one answer.
    """
    if not (ml.water() or ml.pads() or ml.corridors()):
        return np.full(X.shape, BASE_ELEV_M, dtype=np.float32)

    a = math.radians(ml.LAND_MORAINE_GRAIN_DEG)
    c, sn = math.cos(a), math.sin(a)
    wx = ml.LAND_WARP_M * ops.value_noise(X, Y, ml.LAND_WARP_LAM_M, rng_for('warp_x'),
                                          CANVAS_M)
    wy = ml.LAND_WARP_M * ops.value_noise(X, Y, ml.LAND_WARP_LAM_M, rng_for('warp_y'),
                                          CANVAS_M)
    Xw, Yw = X + wx, Y + wy

    # Along the grain and across it. Dividing the along-grain coordinate by the stretch
    # is what makes one wavelength cover more ground in that direction.
    u = (Xw * c + Yw * sn) / ml.LAND_MORAINE_STRETCH
    v = -Xw * sn + Yw * c
    z = (BASE_ELEV_M
         + ml.LAND_MORAINE_M * ops.value_noise(u, v, ml.LAND_MORAINE_LAM_M,
                                               rng_for('moraine'), CANVAS_M)
         + ml.LAND_SWELL_M * ops.value_noise(Xw, Yw, ml.LAND_SWELL_LAM_M,
                                             rng_for('swell'), CANVAS_M)
         + ml.LAND_SWALE_M * ops.value_noise(Xw, Yw, ml.LAND_SWALE_LAM_M,
                                             rng_for('swale'), CANVAS_M))

    return z.astype(np.float32)


def sculpt(z, X, Y):
    """Where the terrain work goes.

    Stages 1, 2, 4 and 5 are built; stage 3 waits on ground that needs it. The build
    order is load-bearing and this is the order:

        1. the landscape        fbm relief, warped, before anything is cut into it
        2. water                carved with `soft_min`, not blended - a weighted blend
                                leaves a band of half-attenuated noise and a valley of
                                constant width, while the smooth minimum leaves the
                                ground outside exactly as it was and puts the rim where
                                the two surfaces cross. The channel holds water, so the
                                profile carried along it is the water **surface** and the
                                bed is cut under it; every later stage takes that wet mask
                                as exempt ground or the channel fills back in.
        3. slope limiting       before the platforms, never after: diffusing a finished
                                embankment ruins it
        4. pads, then corridors yards first, or a road platform overwrites the pad and
                                leaves a step at its edge. Feathers widen with the cut,
                                `max(nominal, 1.5*|dz|/tan(4 deg))`, measured against the
                                land and not against water five metres under it. Built:
                                `grade_pads` levels the four towns, `grade_corridors`
                                cuts the roads and the town streets in on top of them
        5. the rim              last, and by addition (`z + h`), so everything already in
                                the border rides up the flank intact. Built: `build_rim`
                                raises the valley wall around the playable square.

    It refuses rather than ignoring: a layout that carries features this generator does
    not sculpt is the exact failure the shared-geometry rule exists to prevent - the
    vectors would show a river the ground knows nothing about.
    """
    wet = np.zeros(z.shape, dtype=np.float32)
    d_river = None
    if ml.water():
        wet, water_z, d_river = water_fields(X, Y, z)
        z = np.minimum(z, water_z)
    if ml.pads():
        z, built_pads = grade_pads(z, X, Y, wet)
    else:
        built_pads = np.zeros(z.shape, dtype=np.float32)
    if ml.corridors():
        z, built = grade_corridors(z, X, Y, wet)
    else:
        built = np.zeros(z.shape, dtype=np.float32)
    np.maximum(built, built_pads, out=built)
    return z + build_rim(X, Y, d_river), wet, built


BANK_DEG = 4.0            # the slope every feather is sized to hold


def grade_pads(z, X, Y, wet):
    """Stage 4a: level the ground under a yard. Returns the ground and the graded mask.

    Before the corridors and never after: a road platform laid over a finished yard
    overwrites it and leaves a step at the edge of the pad, and driving it is the only
    thing that would show that. It is also what makes the town streets cheap - graded
    onto a platform that is already flat, a 6 m street with an 8 m feather has almost no
    cut to make, which is the only reason a corridor that thin is allowed on a 4 m
    synthesis grid at all.

    Three things here are the ones this pipeline has already been caught by, and they
    are the same three the corridors are:

    * **The platform sits on the ground it replaces.** Its height is the median of the
      land inside the ring, so a town lands on the till plain rather than on the datum -
      which is only the *mean* of the uplands, and would stand a pad on low ground up to
      a storey proud of it.
    * **The feather widens with the cut**, `max(nominal, 1.5*|dz|/tan(4 deg))`, because
      in a smoothstep the steepest gradient is 1.5*rise/run and a constant feather cuts a
      step wherever the platform sits deep. The water is taken out of `dz` before that is
      measured and the weight is kept off it afterwards, for the same reason a road's is:
      against a bed five metres under the floodplain the feather runs away to 170 m and
      fills the channel in.
    * **A pad is not dead flat.** `drain_grade` leaves a residual fall across it, to the
      south, so the yard drains instead of terracing. It is a third of a percent - far
      under any road's ruling grade, so a corridor crossing the pad still holds its own.
    """
    tan_bank = math.tan(math.radians(BANK_DEG))
    built = np.zeros(z.shape, dtype=np.float32)
    for p in ml.pads():
        cx, cy = p['centre']
        w, h = p['size']
        d = ops.rect_sdf(X, Y, cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)
        on = (d <= 0.0) & (wet < 0.25)
        if not bool(on.any()):
            continue
        # The drain tilt is clamped to the pad's own extent. Left to run on, the target
        # plane keeps climbing past the edge of the platform while the ground under it
        # does whatever it does, so `dz` - and with it the feather sized at
        # `1.5*|dz|/tan(4 deg)` - grows with distance instead of settling. On a 310 m
        # pad that is invisible; on a 910 m one it put 6.4 degrees of ground 90 m off
        # the north-west corner, out past any mask, in the middle of what the report
        # calls the uplands. Clamped, the feather has one fixed height to come down
        # from, which is what a feather is.
        sy = np.clip(cy - Y, -h / 2.0, h / 2.0)
        target = (float(np.median(z[on]))
                  + p['drain_grade'] * sy).astype(np.float32)
        dz = target - z
        dry_dz = np.where(wet > 0.25, 0.0, dz)
        feather = np.clip(1.5 * np.abs(dry_dz) / tan_bank, p['feather_m'],
                          FEATHER_CAP_M)
        wgt = (1.0 - ops.smoothstep(d / feather)) * (1.0 - np.clip(wet, 0.0, 1.0))
        z = z + wgt * dz
        np.maximum(built, ops.smoothstep(-d / 8.0), out=built)
    return z, built


def grade_corridors(z, X, Y, wet):
    """Stage 4: cut the roads in. Returns the ground and the graded-ground mask.

    Lower classes first and the trunk roads last, so where two cross it is the higher
    class that keeps its platform - a section road stamped over a primary leaves a step
    across the primary's running surface, and nothing but driving it would show that.

    Three things here are the ones this pipeline has already been caught by:

    * **The profile comes from `limit_grade`**, the mean of the two Lipschitz envelopes.
      It is exact in two passes and balances cut against fill. Clipping the slope
      forward and then backward - the obvious way - is not idempotent and walks the whole
      profile downhill.
    * **The feather widens with the cut**, `max(nominal, 1.5*|dz|/tan(4 deg))`, because
      in a smoothstep the steepest gradient is 1.5*rise/run and a constant feather cuts a
      step wherever the platform sits deep.
    * **Nothing is graded under a bridge, and nothing is graded on water.** The span is
      the one `map_layout.water_crossings` computed and the OSM tags `bridge=yes` from,
      so the deck and the hole in the terrain are the same hole. The ground line the
      profile is fitted to skips the channel too: fitted through it, the road dives 5 m
      into the river and climbs out, and the ruling grade it reports is the riverbank.
    """
    tan_bank = math.tan(math.radians(BANK_DEG))
    x0, y0 = float(X[0, 0]), float(Y[0, 0])
    dx = float(X[0, 1] - X[0, 0])
    built = np.zeros(z.shape, dtype=np.float32)
    rank = {'track': 0, 'street': 0, 'section': 1, 'rail': 2, 'primary': 3}
    for c in sorted(ml.corridors(), key=lambda c: rank.get(c['kind'], 0)):
        dense = ml.densify(c['axis'], 20.0)
        arc = ops.polyline_arclen(dense)
        xs = np.array([p[0] for p in dense])
        ys = np.array([p[1] for p in dense])
        ground = ops.sample_bilinear(z, x0, y0, dx, dx, xs, ys)

        # The ground line the road is fitted to, with the water taken out of it. A span
        # is bridged, so what matters under it is nothing at all; interpolating across
        # gives the profile the abutment-to-abutment chord it actually has to hold.
        onwater = ops.sample_bilinear(wet, x0, y0, dx, dx, xs, ys) > 0.25
        for s0, s1 in c.get('bridge_spans', ()):
            onwater |= (arc >= s0 - 10.0) & (arc <= s1 + 10.0)
        if onwater.all():
            continue
        ground = np.interp(arc, arc[~onwater], ground[~onwater])
        prof = ops.limit_grade(ground, float(arc[1] - arc[0]), c['grade_max'])
        prof = ops.smooth_1d(prof, 1.5)

        half = c['half_width_m']
        reach = half + FEATHER_CAP_M
        d, sarc = ops.polyline_field(X, Y, dense, reach)
        target = np.interp(sarc, arc, prof).astype(np.float32)
        dz = target - z
        feather = np.clip(1.5 * np.abs(dz) / tan_bank, c['feather_m'], FEATHER_CAP_M)
        w = 1.0 - ops.smoothstep((d - half) / feather)

        # Off the water, and off the deck. The abutment is faired over 15 m so the
        # embankment meets the bridge rather than ending at it.
        w = w * (1.0 - np.clip(wet, 0.0, 1.0))
        for s0, s1 in c.get('bridge_spans', ()):
            w = w * (1.0 - ops.smoothstep((sarc - s0) / 15.0)
                     * ops.smoothstep((s1 - sarc) / 15.0))
        z = z + w * dz
        np.maximum(built, ops.smoothstep((half + 0.5 * c['feather_m'] - d) / 8.0),
                   out=built)
    return z, built


def water_fields(X, Y, land):
    """The water: one surface for the river and the lake together, and the wet mask.

    Returns `(wet, water_z, d_river)`. `water_z` is the surface the ground is cut down
    to - the floodplain far from the water, the valley side, the bank, and the bed under
    the waterline, all in one closed-form cross-section. `wet` is where the finished
    ground lies under the waterline; `d_river` is distance to the centreline, which the
    rim needs so it can let the river out of the map.

    Three things here are load-bearing and each of them was a bug on the map before this
    one:

    * **The profile carried along the channel is the water surface, not the bed.** The
      bed is cut under it. Everything downstream - the slope limiter, any platform, the
      texture, the datum's percentile - has to take `wet` as exempt ground, or four
      private opinions about where the water is fill the channel back in on a map that
      still measures as though they had not.
    * **The cross-section reaches the ground it is cut into exactly**, at the waterline
      plus `VALLEY_HALF_W_M`, and it gets there through a smootherstep whose first and
      second derivatives are both zero at that point. It closes on `land`, the local
      height of the till plain, and not on `BASE_ELEV_M`: the datum is only the *mean* of
      the uplands, and a section that closes on the mean subtracts the difference from
      every acre within half a kilometre of the water. Because it closes on the ground
      itself the two surfaces are tangent out there, which is what makes the hard minimum
      exact and a smooth one wrong - see the note where it is taken.
    * **The river is faded out inside the lake.** The axis runs straight over the island,
      and a channel carved there would cut a five-metre notch through it. Inside a lake
      there is no channel; there is a lake.
    """
    ss, sss = ops.smoothstep, ops.smootherstep
    axis = ml.river_axis()
    s_in, s_out, grade, length = ml.river_profile()
    reach = ml.VALLEY_HALF_W_M + ml.RIVER_NOTCH_HALF_M + ml.RIVER_NOTCH_FEATHER_M
    d_river, s_river = ops.polyline_field(X, Y, axis, reach)

    # The water surface: flat across the lake, falling at a constant grade above and
    # below it. Everything else in the cross-section hangs off this, which is what keeps
    # the bank two metres over the water at both ends of a river that drops 2.5 m.
    ws = np.where(s_river < s_in, ml.LAKE_WS_M + grade * (s_in - s_river),
                  np.where(s_river > s_out, ml.LAKE_WS_M - grade * (s_river - s_out),
                           ml.LAKE_WS_M)).astype(np.float32)

    # The valley climbs from the local bank top to the floodplain, and the rise is
    # `BASE_ELEV_M - bank` and not a constant taken off the lake's level. Written as a
    # constant it is only right at the lake: everywhere else the section lands at
    # `ws + 17` instead of at the floodplain, so the river's own 2.5 m of fall was being
    # subtracted from every field within a kilometre and a half of it, with a 1.7 m step
    # where the distance search stopped looking. The playable square measured 73.4 m over
    # ground that is 75.
    hw = ml.RIVER_HALF_W_M
    bank = ws + ml.WATER_BANK_M
    river_z = (ws
               - ml.RIVER_DEPTH_M * (1.0 - ss((d_river - 0.4 * hw) / (0.6 * hw)))
               + ml.WATER_BANK_M * ss((d_river - hw) / ml.BANK_RUN_M)
               + (land - bank)
               * sss((d_river - hw - ml.BANK_RUN_M)
                     / (ml.VALLEY_HALF_W_M - ml.BANK_RUN_M)))

    # The lake. `din` is metres inside its shore, `disl` metres outside the island's;
    # both come from `ellipse_r` on the constants the drawn rings are built from, so the
    # water is painted exactly where the basin is.
    # `ellipse_r` is a *normalised* radius - 1 on the shore - and turning it into metres
    # by multiplying by a mean radius is not the same thing as a distance. On a lake half
    # again as long as it is wide, and with a lobed shore on top of that, it compresses
    # the section by a fifth on the short axis and more where a lobe turns: the valley
    # came out 400 m wide instead of 500 on the north shore and its rim measured 12
    # degrees against the 5 it is built to. Dividing by the gradient of the field is what
    # makes it a distance, and it costs two `np.gradient` calls.
    dx = float(X[0, 1] - X[0, 0])
    q = ops.ellipse_r(X, Y, *ml.LAKE_C, ml.LAKE_A, ml.LAKE_B, ml.LAKE_ROT,
                      ml.LAKE_HARMONICS)
    qi = ops.ellipse_r(X, Y, *ml.LAKE_C, ml.ISLAND_A, ml.ISLAND_B, ml.LAKE_ROT)
    din = (1.0 - q) / ops.grad_mag(q, dx)
    disl = (qi - 1.0) / ops.grad_mag(qi, dx)
    lake_z = (ml.LAKE_WS_M
              - ml.LAKE_DEPTH_M * ss(din / ml.LAKE_SHELF_M) * ss(disl / ml.LAKE_SHELF_M)
              + ml.ISLAND_H_M * ss(-disl / ml.ISLAND_RISE_M)
              + ml.WATER_BANK_M * ss(-din / ml.BANK_RUN_M)
              + (land - ml.LAKE_WS_M - ml.WATER_BANK_M)
              * sss((-din - ml.BANK_RUN_M) / (ml.VALLEY_HALF_W_M - ml.BANK_RUN_M)))

    # Off the lake entirely the expression above is meaningless, but it is also far above
    # the ground by then, so the minimum simply never selects it. Pinning it high past
    # that keeps it that way without a discontinuity anywhere the two surfaces are within
    # blending distance of each other.
    lake_z = np.where(din > -ml.VALLEY_HALF_W_M, lake_z, 1.0e4).astype(np.float32)
    # The river is switched off over the island and nowhere else. Switching it off at the
    # lake shore instead - the obvious place - is what put the steepest slope on the
    # playable map right across the river's mouth: the channel arrives three metres under
    # the waterline, the lake's littoral shelf is barely wet that close in, and the two
    # were being swapped over a few tens of metres. Left alone they need no swap at all,
    # because the minimum of the two already scours the channel across the shelf and
    # hands over to the basin as the basin gets deeper, which is what a river entering a
    # lake actually does. The island is the one place the lake bed comes back up over the
    # channel, and a three-metre notch cut through an island is what the fade is for.
    river_z = river_z + (1.0e4 - river_z) * ss((ml.ISLAND_RISE_M - disl)
                                               / ml.ISLAND_RISE_M)

    water_z = ops.soft_min(river_z, lake_z, WATER_BLEND_M)
    wet = np.maximum(ss((ws - river_z) / 0.5) * (din <= 0.0),
                     ss((ml.LAKE_WS_M - lake_z) / 0.5))
    return wet.astype(np.float32), water_z, d_river


def rim_crest(X, Y):
    """Where the summits are around the rim and how high, as `(along, u, crest_abs)`.

    Split out of `build_rim` because the east range's *foot* has to follow its own crest:
    a spur runs out from a summit and a re-entrant sits under a saddle, so the toe cannot
    be worked out until the crest is. `u` is the dimensionless height in the saddle-to-
    crest band, and the measurer reads this too, so "where the summits are" has one
    answer.

    Two things here are load-bearing:

    * The ridge line is closed form - two sines beating against each other around the
      perimeter - rather than an RNG walk, so it comes out identically every run whatever
      else is added to the terrain first. The lobe counts are whole numbers because
      `along` wraps, and coprime so the pair beats over the whole ring and no two summits
      along the 8 km of a range come out at the same height.
    * `u` is built in the *dimensionless* band between the saddles and the summits and
      only then mapped to metres, so the crest cannot leave 200 .. 250 m on a range
      however the noise falls. `tanh` rather than a clip does the containing: a clip
      flattens the top of every summit that reaches for the ceiling into a plateau at
      exactly 250.00 m.
    """
    along = ops.rim_along(X, Y, PLAYABLE_M)
    tau = 2.0 * np.pi
    n_spur = ops.value_noise(X, Y, ml.RIM_SPUR_LAM_M, rng_for('rim_spur'), CANVAS_M)
    n_rough = ops.value_noise(X, Y, ml.RIM_ROUGH_LAM_M, rng_for('rim_rough'), CANVAS_M)
    ridge = (0.35 * np.sin(tau * ml.RIM_RIDGE_LOBES * along)
             + 0.15 * np.sin(tau * ml.RIM_RIDGE_BEAT * along + 1.1)
             + ml.RIM_SPUR_AMP * n_spur + ml.RIM_ROUGH_AMP * n_rough)

    # The west range reads smoother than the east. Damping `ridge` is the right place to
    # do it: it pulls the crest toward the middle of the saddle-to-crest band without
    # touching the band, so the west still climbs to a mountain range and simply wanders
    # less on the way along it. The selector is a function of X alone and turns over
    # inside the playable square, where the rim is identically zero - so however abrupt
    # it is, it cannot put a seam in any ground that exists.
    ridge = ridge * (1.0 - (1.0 - ml.RIM_WEST_SMOOTH)
                     * ops.smoothstep((0.5 * PLAYABLE_M - X) / (0.5 * PLAYABLE_M)))
    u = 0.5 + 0.5 * np.tanh(2.0 * ridge)                       # (0, 1), no plateaus
    peak = ml.RIM_SADDLE_M + (ml.RIM_CREST_M - ml.RIM_SADDLE_M) * u
    sill = ml.RIM_MOUTH_M + ml.RIM_MOUTH_VAR_M * (0.6 * n_spur + 0.4 * n_rough)
    return along, u, peak, sill


def rim_ramp(X, Y):
    """`(t, w)` for the rim, with the east range's toe following its own crest.

    The measurer takes its strips from this, so the two halves cannot disagree about
    where a range is or how far in it reaches.
    """
    _, u, _, _ = rim_crest(X, Y)
    toe = ml.RIM_EAST_TOE_X + ml.RIM_EAST_WANDER_M * (1.0 - u)
    _, t, w = ops.rim_field(X, Y, PLAYABLE_M, ml.RIM_APRON_M, ml.RIM_BACK_M, OFFSET_M,
                            east=(toe, ml.RIM_EAST_WARP_K))
    return t, w


def rim_crest(X, Y):
    """Where the summits are around the rim and how high: `(u, peak, sill)`.

    Split out of `build_rim` because the west range's *foot* has to follow its own crest -
    a spur runs out from a summit and a re-entrant sits under a saddle - so the toe cannot
    be worked out until the crest is. `u` is the dimensionless height in the saddle-to-
    crest band; the measurer reads this through `rim_ramp`, so "where the summits are" has
    one answer.

    Two things here are load-bearing:

    * The ridge line is closed form - two sines beating against each other around the
      perimeter - rather than an RNG walk, so it comes out identically every run whatever
      else is added to the terrain first. The lobe counts are whole numbers because
      `along` wraps, and coprime so the pair beats over the whole ring and no two summits
      along the 8 km of a range come out at the same height.
    * `u` is built in the *dimensionless* band between the saddles and the summits and
      only then mapped to metres, so the crest cannot leave 200 .. 250 m on a range
      however the noise falls. `tanh` rather than a clip does the containing: a clip
      flattens the top of every summit that reaches for the ceiling into a plateau at
      exactly 250.00 m.
    """
    along = ops.rim_along(X, Y, PLAYABLE_M)
    tau = 2.0 * np.pi
    n_spur = ops.value_noise(X, Y, ml.RIM_SPUR_LAM_M, rng_for('rim_spur'), CANVAS_M)
    n_rough = ops.value_noise(X, Y, ml.RIM_ROUGH_LAM_M, rng_for('rim_rough'), CANVAS_M)
    ridge = (0.35 * np.sin(tau * ml.RIM_RIDGE_LOBES * along)
             + 0.15 * np.sin(tau * ml.RIM_RIDGE_BEAT * along + 1.1)
             + ml.RIM_SPUR_AMP * n_spur + ml.RIM_ROUGH_AMP * n_rough)

    # The west range reads smoother than the east. Damping `ridge` is the right place to
    # do it: it pulls the crest toward the middle of the saddle-to-crest band without
    # touching the band, so the west still climbs to a mountain range and simply wanders
    # less along it. The selector is a function of X alone and turns over inside the
    # playable square, where the rim is identically zero on both
    # sides, so however abrupt it is it cannot put a seam in any ground that exists.
    ridge = ridge * (1.0 - (1.0 - ml.RIM_WEST_SMOOTH)
                     * ops.smoothstep((0.5 * PLAYABLE_M - X) / (0.5 * PLAYABLE_M)))
    u = 0.5 + 0.5 * np.tanh(2.0 * ridge)                       # (0, 1), no plateaus
    peak = ml.RIM_SADDLE_M + (ml.RIM_CREST_M - ml.RIM_SADDLE_M) * u
    sill = ml.RIM_MOUTH_M + ml.RIM_MOUTH_VAR_M * (0.6 * n_spur + 0.4 * n_rough)
    return u, peak, sill


def rim_ramp(X, Y):
    """`(t, w)` for the rim. The measurer takes its strips from this, so the two halves
    cannot disagree about where a range is."""
    _, t, w = ops.rim_field(X, Y, PLAYABLE_M, ml.RIM_APRON_M, ml.RIM_BACK_M, OFFSET_M)
    return t, w


def build_rim(X, Y, d_river=None):
    """The valley wall: two ranges east and west, a sill north and south.

    The whole thing is one height field, `t * (crest - datum)`, where `t` is the ramp out
    of the toe and `crest` is the elevation the rim reaches directly out from each pixel.
    The relief on the flank is the *horizontal* variation of `crest` scaled by `t`, so a
    summit and the saddle beside it grow their own spurs and re-entrants down the slope
    for free, and every one of them lands on the crest line rather than 30 m above it.
    Adding the texture on top of a finished ramp instead would push the summits straight
    through the 250 m the brief allows.

    Every side starts one apron past the playable boundary, so none of the rim is ground
    the player can reach and the playable square keeps its own relief right up to the
    edge.
    """
    _, peak, sill = rim_crest(X, Y)
    t, w = rim_ramp(X, Y)
    crest = sill + (peak - sill) * w
    lift = t * np.maximum(crest - BASE_ELEV_M, 0.0)

    # Let the river out. The rim is added on top of whatever is already in the border, so
    # over the channel it would lift the water forty metres on its way off the map - the
    # sill damming the river it is supposed to let through. The notch is wider than the
    # valley and feathered wider than the sill is tall, so what is left either side of the
    # water is a shoulder and not a gorge wall.
    if d_river is not None:
        lift = lift * ops.smoothstep((d_river - ml.RIVER_NOTCH_HALF_M)
                                     / ml.RIVER_NOTCH_FEATHER_M)
    return lift


# ==================================================================================
# output
# ==================================================================================
def write_stats(z, X, Y, path):
    """A coarse height and roughness grid for the OSM generator.

    The parcelling wants smaller fields on broken ground. Rather than have it re-derive
    the terrain (two implementations of one landscape, guaranteed to drift) or pull a
    150 megapixel PNG through numpy in a standard-library-only folder, the DEM publishes
    what it already knows, in JSON. On a flat map every cell reads 0 roughness.
    """
    p0 = int(OFFSET_M / WORK_DX)
    p1 = int((OFFSET_M + PLAYABLE_M) / WORK_DX)
    play = z[p0:p1, p0:p1]
    slope = np.tan(np.radians(ops.slope_deg(play, WORK_DX, baseline_m=40.0)))
    k = play.shape[0] // STATS_GRID
    hgt = play.reshape(STATS_GRID, k, STATS_GRID, k).mean(axis=(1, 3))
    slp = slope.reshape(STATS_GRID, k, STATS_GRID, k).mean(axis=(1, 3))
    rough = np.clip(slp / ROUGH_FULL_SCALE, 0.0, 1.0)
    with open(path, 'w') as fh:
        json.dump({'n': STATS_GRID, 'cell_m': PLAYABLE_M / STATS_GRID,
                   'origin': [0.0, 0.0],
                   'height': [round(float(v), 2) for v in hgt.ravel()],
                   'roughness': [round(float(v), 4) for v in rough.ravel()]}, fh)


def write_dem(z_work, built_work, out_path):
    """Resample to 1 m and quantise, one band at a time.

    Never materialises a full-resolution float array: the output is a preallocated uint16
    and each band is 1024 rows. Peak memory is about half a gigabyte instead of five.

    `built_work` is the graded-ground mask - the micro-relief is damped to a sixth of its
    amplitude on a platform, because a running surface is graded and gravel, not prairie.
    """
    n = CANVAS_M
    out = np.empty((n, n), dtype=np.uint16)
    cols = (np.arange(n, dtype=np.float32) + 0.5 - WORK_DX * 0.5) / WORK_DX

    lattice = None
    if MICRO_AMP_M > 0.0:
        rng_micro = rng_for('micro')
        lattice_n = int(CANVAS_M / MICRO_LAM_M) + 4
        lattice = rng_micro.standard_normal((lattice_n, lattice_n)).astype(np.float32)
        lattice /= lattice.std()
    rng_dither = rng_for('dither')

    for b in range(n // BAND_ROWS):
        r0, r1 = b * BAND_ROWS, (b + 1) * BAND_ROWS
        rows = (np.arange(r0, r1, dtype=np.float32) + 0.5 - WORK_DX * 0.5) / WORK_DX
        coords = np.stack(np.broadcast_arrays(rows[:, None], cols[None, :]))
        band = ndimage.map_coordinates(z_work, coords, order=3, mode='nearest',
                                       output=np.float32)
        if lattice is not None:
            blt = ndimage.map_coordinates(built_work, coords, order=1, mode='nearest',
                                          output=np.float32)
            mcoords = np.stack(np.broadcast_arrays(
                (np.arange(r0, r1, dtype=np.float32) / MICRO_LAM_M)[:, None],
                (np.arange(n, dtype=np.float32) / MICRO_LAM_M)[None, :]))
            micro = ndimage.map_coordinates(lattice, mcoords, order=3,
                                            mode='grid-wrap', output=np.float32)
            band += MICRO_AMP_M * micro * (1.0 - 0.85 * np.clip(blt, 0.0, 1.0))
        band *= 100.0
        if DITHER_CM > 0.0:
            # triangular dither: decorrelates the rounding error from the surface, so a
            # flat yard shows grain instead of contour bands
            band += DITHER_CM * (rng_dither.random(band.shape, dtype=np.float32)
                                 + rng_dither.random(band.shape, dtype=np.float32) - 1.0)
        np.clip(band, 0.0, Z_MAX_CM, out=band)
        out[r0:r1] = np.rint(band).astype(np.uint16)
    Image.fromarray(out).save(out_path)
    return out


# ==================================================================================
# figures
# ==================================================================================
def style(ax, title):
    ax.set_xlabel("X (East-West) [metres]", fontsize=11, fontweight='bold')
    ax.set_ylabel("Y (North-South) [metres]", fontsize=11, fontweight='bold')
    ax.grid(True, which='both', color='white', linestyle='--', linewidth=0.5, alpha=0.35)
    ax.tick_params(colors='white')
    for spine in ax.spines.values():
        spine.set_color('white')
    ax.yaxis.label.set_color('white')
    ax.xaxis.label.set_color('white')
    ax.set_title(title, fontsize=15, fontweight='bold', pad=14, color='white')


def shade(sub, vmin, vmax):
    ls = LightSource(azdeg=315, altdeg=45)
    return ls.shade(sub, cmap=plt.get_cmap('terrain'), blend_mode='overlay',
                    vert_exag=2.0, vmin=vmin, vmax=vmax)


def draw_layout(ax):
    """The layout on top of the terrain: if the two disagree, it shows here."""
    for c in ml.corridors():
        if c['kind'] in ('track', 'street'):
            continue
        ax.plot([p[0] for p in c['axis']], [p[1] for p in c['axis']],
                color=('#F59E0B' if c['kind'] == 'rail' else '#E5E7EB'),
                lw=(1.6 if c['kind'] == 'rail' else 0.9),
                ls=('--' if c['kind'] == 'rail' else '-'), alpha=0.85)
    for w in ml.water():
        if w.get('ring'):
            ax.fill([p[0] for p in w['ring']], [p[1] for p in w['ring']],
                    color='#0284C7', alpha=0.75)
        elif w.get('axis'):
            ax.plot([p[0] for p in w['axis']], [p[1] for p in w['axis']],
                    color='#38BDF8', lw=1.8)
    for p in ml.pads():
        ax.plot([q[0] for q in p['ring']], [q[1] for q in p['ring']],
                color={'industry': '#6366F1', 'farm': '#22C55E'}.get(
                    p.get('kind'), '#DB2777'), lw=1.2)


def draw_figures(raw, out_vis, out_detail):
    n = CANVAS_M
    k = n // 1024
    vis = raw.reshape(1024, k, 1024, k).mean(axis=(1, 3)) / 100.0
    vmin, vmax = np.percentile(vis, 0.5), np.percentile(vis, 99.5)
    # A flat canvas has no range to stretch a colour map over, and the hillshade would
    # divide by zero. Half a metre either side gives it something to work with and reads
    # as the single flat tone it is.
    if vmax - vmin < 1e-6:
        vmin, vmax = vmin - 0.5, vmax + 0.5

    fig, ax = plt.subplots(figsize=(11, 11), dpi=150)
    fig.patch.set_facecolor('#111111')
    ax.set_facecolor('#111111')
    ax.imshow(shade(vis, vmin, vmax), extent=[0, n, n, 0])
    im = ax.imshow(vis, extent=[0, n, n, 0], cmap='terrain', vmin=vmin, vmax=vmax,
                   alpha=0.0)
    ax.set_xticks(np.arange(0, n + 1, 1024))
    ax.set_yticks(np.arange(0, n + 1, 1024))
    style(ax, f"Full DEM canvas ({n}x{n} px, 1 px = 1 m)")
    ax.add_patch(plt.Rectangle((OFFSET_M, OFFSET_M), PLAYABLE_M, PLAYABLE_M, fill=False,
                               edgecolor='white', linewidth=2, linestyle='--',
                               label=f'Playable border ({PLAYABLE_M / 1000:.1f} km)'))
    ax.legend(loc='upper right', facecolor='black', labelcolor='white', fontsize=9)
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("height [m]", color='white')
    cb.ax.tick_params(colors='white')
    cb.outline.set_edgecolor('white')
    plt.savefig(out_vis, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close()

    p0 = (OFFSET_M * 1024) // n
    p1 = ((OFFSET_M + PLAYABLE_M) * 1024) // n
    sub = vis[p0:p1, p0:p1]
    fig, ax = plt.subplots(figsize=(10, 10), dpi=150)
    fig.patch.set_facecolor('#111111')
    ax.set_facecolor('#111111')
    ax.imshow(shade(sub, vmin, vmax), extent=[0, PLAYABLE_M, PLAYABLE_M, 0])
    im = ax.imshow(sub, extent=[0, PLAYABLE_M, PLAYABLE_M, 0], cmap='terrain',
                   vmin=vmin, vmax=vmax, alpha=0.0)
    if sub.max() - sub.min() > 2.0:
        xs = np.linspace(0, PLAYABLE_M, sub.shape[1])
        ax.contour(xs, xs, sub, levels=np.arange(np.floor(sub.min()), sub.max(), 2.0),
                   colors='white', linewidths=0.4, alpha=0.25)
    draw_layout(ax)
    ax.set_xticks(np.arange(0, PLAYABLE_M + 1, 1024))
    ax.set_yticks(np.arange(0, PLAYABLE_M + 1, 1024))
    style(ax, f"Playable area ({PLAYABLE_M / 1000:.1f} x {PLAYABLE_M / 1000:.1f} km)")
    ax.set_xlim(0, PLAYABLE_M)
    ax.set_ylim(PLAYABLE_M, 0)
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("height [m]", color='white')
    cb.ax.tick_params(colors='white')
    cb.outline.set_edgecolor('white')
    plt.savefig(out_detail, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close()


# ==================================================================================
# The non-playable border comes from the source DEM verbatim, and that border carries
# four straight channels - the outlets of a river this map no longer has - cut from the
# playable boundary clean through the valley wall to the canvas edge, a pair at each of
# two opposite corners. They are the only breaches in the rim, and closing the horizon is
# the whole of what the rim is for.
#
# The repair is written as a property of the ground rather than as four rectangles,
# because four rectangles stop being right the day the source DEM changes. A *trench* is
# anything a grey closing this wide has to fill by more than BORDER_TRENCH_M; a *breach*
# is a trench that runs the whole depth of the border, touching the canvas edge at one end
# and the apron at the other. The border's own saddles and re-entrants are trenches too -
# the detector finds around eighty of them - and every one fails the second half of that
# test, because a saddle in a range is open at one end and not at both.
BORDER_BRIDGE_M = 141.0     # the widest trench the repair will bridge
BORDER_TRENCH_M = 3.0       # ... and how deep it has to be before it counts as one
BORDER_GROW_M = 80.0        # grow the mask onto ground the trench never touched: anchored
                            # on the trench's own flank the fill lands four metres out
BORDER_SCAN_PX = 4          # the border is smooth at 1 m/px; detect and fill at 4 m


def _inpaint(sub, m):
    """Replace `sub[m]` with a smooth surface that meets the ground around it.

    Nearest-neighbour first so nothing starts at a wild value, then relaxation under a
    Gaussian from coarse to fine with everything outside the mask held fixed - which is
    diffusion again, and converges on the harmonic fill through the boundary values. The
    coarse passes carry the shape of the ridge across the gap; the fine ones take the
    kink out of where the fill meets the ground.
    """
    _, idx = ndimage.distance_transform_edt(m, return_indices=True)
    sub[m] = sub[idx[0][m], idx[1][m]]
    for sigma in (16.0, 12.0, 8.0, 6.0, 4.0, 3.0, 2.0, 1.5, 1.0):
        for _ in range(10):
            sub[m] = ndimage.gaussian_filter(sub, sigma)[m]
    return sub


def fill_border_trenches(raw):
    """Close every channel cut clean through the non-playable border. In place.

    Detection and the fill both run on a `BORDER_SCAN_PX` reduction of the canvas: the
    border is a smooth surface - nowhere in it does the source DEM step more than 30 cm
    between neighbouring metres - so a quarter-resolution grid holds everything the
    repair needs, and a 141 m closing over 150 megapixels does not.

    Only the correction comes back to full resolution, interpolated over the boxes it is
    nonzero in. It is zero outside the mask by construction, so no ground the trenches
    never reached is touched, and the playable square is outside it twice over.
    """
    k = BORDER_SCAN_PX
    n = raw.shape[0]
    m = n // k
    z = (raw.reshape(m, k, m, k).mean(axis=(1, 3)) / 100.0).astype(np.float32)

    # Metres out of the playable square, at the centre of each coarse cell.
    c = np.arange(m, dtype=np.float32) * k + 0.5 * k
    dc = np.maximum(0.0, np.maximum(OFFSET_M - c, c - (OFFSET_M + PLAYABLE_M)))
    d_out = np.hypot(dc[None, :], dc[:, None])

    w = max(3, int(round(BORDER_BRIDGE_M / k)) | 1)
    deficit = ndimage.grey_closing(z, size=(w, w), mode='nearest') - z
    trench = (deficit > BORDER_TRENCH_M) & (d_out >= ml.RIM_APRON_M)
    lbl, _ = ndimage.label(trench)

    # A breach runs the whole depth of the border: it reaches the canvas edge and it
    # reaches the apron. A saddle does one or the other and is left where it is.
    at_edge = np.zeros(trench.shape, dtype=bool)
    at_edge[0] = at_edge[-1] = True
    at_edge[:, 0] = at_edge[:, -1] = True
    at_apron = d_out < ml.RIM_APRON_M + k
    keep = sorted((set(np.unique(lbl[at_edge & trench])) - {0})
                  & (set(np.unique(lbl[at_apron & trench])) - {0}))
    if not keep:
        return raw, 0

    # Grown onto undisturbed ground either side, and never inside the playable square.
    mask = ndimage.distance_transform_edt(~np.isin(lbl, keep)) <= BORDER_GROW_M / k
    mask &= d_out > 0.0

    delta = np.zeros_like(z)
    parts, _ = ndimage.label(mask)
    for i, (sy, sx) in enumerate(ndimage.find_objects(parts), 1):
        pad = 2 * w
        y0, y1 = max(0, sy.start - pad), min(m, sy.stop + pad)
        x0, x1 = max(0, sx.start - pad), min(m, sx.stop + pad)
        sub, mm = z[y0:y1, x0:x1].copy(), mask[y0:y1, x0:x1]
        delta[y0:y1, x0:x1] = _inpaint(sub, mm) - z[y0:y1, x0:x1]

    # Back to full resolution, one box at a time. Coarse cell j spans [jk, jk+k), so the
    # coarse coordinate of output pixel i is (i + 0.5)/k - 0.5.
    for sy, sx in ndimage.find_objects(parts):
        y0, y1 = max(0, sy.start - 1) * k, min(m, sy.stop + 1) * k
        x0, x1 = max(0, sx.start - 1) * k, min(m, sx.stop + 1) * k
        rr = (np.arange(y0, y1, dtype=np.float32) + 0.5) / k - 0.5
        cc = (np.arange(x0, x1, dtype=np.float32) + 0.5) / k - 0.5
        d = ndimage.map_coordinates(
            delta, np.meshgrid(rr, cc, indexing='ij'), order=1, mode='nearest')
        box = raw[y0:y1, x0:x1].astype(np.float32) + d * 100.0
        raw[y0:y1, x0:x1] = np.rint(np.clip(box, 0.0, 65535.0)).astype(np.uint16)

    return raw, len(keep)


# ==================================================================================
# The ridge in the east of the map dies before it gets out: the crest holds its height
# across the uplands and then collapses over the last two hundred metres of playable
# ground, so the range ends in a cliff at the boundary with the border's own mountains
# standing clear of it. Running it on is one operation and not two - the ground inside the
# map and the ground outside it are the same ridge - so it is done on the whole canvas at
# once, and the apron is blended afterwards against the ground this leaves rather than
# against the ground that was there before.
#
# The construction is a swept cross-section: the last station where the ridge still stands
# is the donor, and its section is carried east, losing EAST_RIDGE_SAG_M to a col on the
# way, until the border range rises over it and a maximum hands the ground back. Nothing
# says where the range ends, which is the point - it ends where it meets the other one.
EAST_RIDGE_KEEP = 0.90       # the donor is the last station standing this high
EAST_RIDGE_SEARCH_M = 1500.0 # ... looked for over this much of the ridge's own length
EAST_RIDGE_SAG_M = 25.0      # the col between the two ranges
EAST_RIDGE_SAG_RUN_M = 500.0 # ... reached over this much of the run
EAST_RIDGE_FEATHER_M = 200.0 # the section is carried to nothing over this, either side
EAST_RIDGE_BLUR_M = 25.0     # rounds the break the swept section makes at the donor


def extend_east_ridge(raw):
    """Run the eastern ridge across the boundary and into the border range. In place.

    The band it works in is the wood's own: the timber is what is drawn on this ridge, so
    the ring is the one record of where the ridge is, and taking the band from anywhere
    else would be a second opinion about a thing the layout already states. The section is
    added rather than written - `maximum` against the ground that is there - which is what
    makes the far end need no constant: over the flanks of the border range the range is
    already higher and the operation does nothing at all.
    """
    ring = getattr(ml, 'EAST_RIDGE_RING', None) or next(
        (a['ring'] for a in ml.AREAS if a['id'] == f'wood_{ml.EAST_RIDGE_WAY}'), None)
    if ring is None:
        return raw, None

    x_east = max(p[0] for p in ring)
    tip = [p for p in ring if p[0] > x_east - ml.EAST_WOOD_STRETCH_M]
    y0 = min(p[1] for p in tip) - EAST_RIDGE_FEATHER_M
    y1 = max(p[1] for p in tip) + EAST_RIDGE_FEATHER_M

    r0 = max(0, int(round(y0)) + OFFSET_M)
    r1 = min(raw.shape[0], int(round(y1)) + OFFSET_M)
    c_end = int(round(x_east)) + OFFSET_M
    c_lo = max(0, c_end - int(EAST_RIDGE_SEARCH_M))
    z = raw[r0:r1, c_lo:].astype(np.float32) / 100.0

    # The donor: the easternmost station whose crest still stands at EAST_RIDGE_KEEP of
    # the best the ridge makes over the search. Read off the ground rather than set as a
    # setback from the boundary, because how far in the collapse reaches is a property of
    # the source DEM and not of the map.
    crest = z[:, :c_end - c_lo].max(axis=0)
    j0 = int(np.nonzero(crest >= EAST_RIDGE_KEEP * crest.max())[0].max())

    xs = np.arange(z.shape[1] - j0, dtype=np.float32)
    drop = EAST_RIDGE_SAG_M * ops.smoothstep(xs / EAST_RIDGE_SAG_RUN_M)
    ys = np.arange(r0, r1, dtype=np.float32) - OFFSET_M
    w = ops.smoothstep(np.minimum(ys - y0, y1 - ys) / EAST_RIDGE_FEATHER_M)

    blk = z[:, j0:]
    lift = np.maximum(0.0, z[:, j0][:, None] - drop[None, :] - blk) * w[:, None]
    # The swept section meets the collapsing ridge in a break line at the donor. Blurring
    # the lift rounds it off without touching the ridge itself: the lift is zero over
    # everything the extension does not reach, so what the blur spreads there is zero.
    lift = ndimage.gaussian_filter(lift, EAST_RIDGE_BLUR_M)
    z[:, j0:] = blk + lift
    raw[r0:r1, c_lo:] = np.rint(np.clip(z * 100.0, 0.0, 65535.0)).astype(np.uint16)
    return raw, (c_lo + j0 - OFFSET_M, float(lift.max()))


# ==================================================================================
def clean_town_and_reservoir_area(valle_play):
    """Cleans and restores the region previously occupied by the town and water reservoir
    (x in [6930, 8192], y in [0, 2400]). Removes all artificial flattening, reservoir depressions,
    and filter seams, providing a smooth natural continuation of the landscape and clean
    transition to the mountain.
    """
    out = valle_play.copy()
    ref_col = valle_play[0:2400, 6930].copy()

    # 1. Natural continuation of the plain and gentle slope across x in [6930, 8192]
    out[0:2260, 6930:8192] = ref_col[0:2260, None]

    # 2. Smooth blend into the natural mountain foot for y in [2260, 2400]
    for y in range(2260, 2400):
        t = (y - 2260) / (2400 - 2260)
        w = t * t * (3.0 - 2.0 * t)
        orig = np.maximum(ref_col[y], valle_play[y, 6930:8192])
        out[y, 6930:8192] = (1.0 - w) * ref_col[y] + w * orig

    return out


TILL_PX = 4                  # the till relief is built at this pitch and resampled, like
                             # the synthesis: nothing in it is under 110 m of wavelength
TILL_FLAT_TOL_M = 0.005      # "exactly the datum of the flat strip", half a centimetre


def till_weight(z4, dx=float(TILL_PX)):
    """Where the till relief goes, on a `dx` m grid of the playable square.

    Returns `(w_geo, w_ridge)`, both 0..1. `w_geo` is the hard geography - zero on the
    lake and its shore, along the playable boundary and over the deliberately flat strip
    - and `w_ridge` is 1 on the till and 0 on the eastern ridge, read off the ground's own
    height and slope. The measurer takes its "what is till" from this same call, so the
    surface that is judged is the one that was built.

    The flat strip is *detected*, not drawn: it is every region of `TILL_FLAT_MIN_HA` or
    more where the source DEM sits at one height to the half-centimetre. The source is
    the only record of where that strip is, and a rectangle written here would stop
    being right the day it changes. Isolated pixels that happen to land on the same
    value are opened away first, or each would punch a fade-sized hole in the relief.
    """
    sss = ops.smootherstep
    n = z4.shape[0]
    ax = (np.arange(n, dtype=np.float32) + 0.5) * dx
    X, Y = ax[None, :], ax[:, None]

    # The boundary.
    d_edge = np.minimum(np.minimum(X, ml.PLAYABLE_M - X), np.minimum(Y, ml.PLAYABLE_M - Y))
    w = sss(d_edge / ml.TILL_EDGE_FADE_M)

    # The lake and its shore, from the ring the lake is carved from.
    for wb in ml.water():
        if not wb.get('ring'):
            continue
        img = Image.new('L', (n, n), 0)
        ImageDraw.Draw(img).polygon([(x / dx, y / dx) for x, y in wb['ring']],
                                    outline=1, fill=1)
        lake = np.array(img, dtype=bool)
        d_out = ndimage.distance_transform_edt(~lake) * dx
        w = w * sss((d_out - ml.TILL_SHORE_CLEAR_M) / ml.TILL_SHORE_FADE_M)

    # The flat strip: one height, held over a region big enough to be meant.
    k5 = max(3, int(round(20.0 / dx)) | 1)
    flat = (ndimage.maximum_filter(z4, size=k5)
            - ndimage.minimum_filter(z4, size=k5)) < TILL_FLAT_TOL_M
    flat = ndimage.binary_opening(flat, iterations=max(1, int(48.0 / dx)))
    lbl, k = ndimage.label(flat)
    if k:
        sizes = ndimage.sum(flat, lbl, index=np.arange(1, k + 1)) * dx * dx / 1.0e4
        keep = np.isin(lbl, 1 + np.nonzero(sizes >= ml.TILL_FLAT_MIN_HA)[0])
        if keep.any():
            d_flat = ndimage.distance_transform_edt(~keep) * dx
            w = w * sss(d_flat / ml.TILL_FLAT_FADE_M)

    # The ridge, off the ground itself. Blurred so the fade has no contour of its own.
    z0, z1 = ml.TILL_RIDGE_Z_M
    s0, s1 = ml.TILL_RIDGE_SLOPE_DEG
    slope = ops.slope_deg(z4, dx, baseline_m=20.0)
    w_ridge = (1.0 - sss((z4 - z0) / (z1 - z0))) * (1.0 - sss((slope - s0) / (s1 - s0)))
    w_ridge = ndimage.gaussian_filter(w_ridge.astype(np.float32), 40.0 / dx)
    return w.astype(np.float32), w_ridge.astype(np.float32)


def roughen_till(valle_play):
    """Add the till's swell and swale to the playable square. Returns a new array.

    The source DEM has the moraines and nothing much under 400 m; this is the relief
    between 110 and 450 m that a field in the Des Moines lobe actually has - see the
    `TILL_*` block in the layout for the octaves. Built on a `TILL_PX` m grid, weighted
    by `till_weight`, and resampled to 1 m with the same cubic kernel the synthesis uses.

    It runs before the platforms and before the lake: a platform is levelled over
    whatever ground it stands on, and the lake carves whatever it meets, so both come
    out exactly as they would have without this, on ground that now rolls up to them.
    """
    n1 = valle_play.shape[0]
    n = n1 // TILL_PX
    dx = float(TILL_PX)
    z4 = valle_play.reshape(n, TILL_PX, n, TILL_PX).mean(axis=(1, 3)).astype(np.float32)
    ax = (np.arange(n, dtype=np.float32) + 0.5) * dx
    X, Y = np.meshgrid(ax, ax)
    span = float(ml.PLAYABLE_M)

    wx = ml.TILL_WARP_M * ops.value_noise(X, Y, ml.TILL_WARP_LAM_M,
                                          rng_for('till_warp_x'), span)
    wy = ml.TILL_WARP_M * ops.value_noise(X, Y, ml.TILL_WARP_LAM_M,
                                          rng_for('till_warp_y'), span)
    Xw, Yw = X + wx, Y + wy
    a = math.radians(ml.LAND_MORAINE_GRAIN_DEG)
    c, sn = math.cos(a), math.sin(a)
    u = (Xw * c + Yw * sn) / ml.TILL_SWELL_STRETCH
    v = -Xw * sn + Yw * c
    swell = ml.TILL_SWELL_M * ops.value_noise(u, v, ml.TILL_SWELL_LAM_M,
                                              rng_for('till_swell'), span)
    swale = ml.TILL_SWALE_M * ops.value_noise(Xw, Yw, ml.TILL_SWALE_LAM_M,
                                              rng_for('till_swale'), span)
    knob = ml.TILL_KNOB_M * ops.value_noise(Xw, Yw, ml.TILL_KNOB_LAM_M,
                                            rng_for('till_knob'), span)

    w_geo, w_ridge = till_weight(z4, dx)
    lift = w_geo * (w_ridge * (swell + swale + knob)
                    + (1.0 - w_ridge) * ml.TILL_RIDGE_KEEP * swale)

    # To 1 m, banded like `write_dem`. Grid pixel j is centred at dx*j + dx/2, so output
    # pixel i (centre i + 0.5) sits at grid coordinate (i + 0.5 - dx/2) / dx.
    out = valle_play.copy()
    cols = (np.arange(n1, dtype=np.float32) + 0.5 - dx * 0.5) / dx
    for r0 in range(0, n1, BAND_ROWS):
        r1 = min(n1, r0 + BAND_ROWS)
        rows = (np.arange(r0, r1, dtype=np.float32) + 0.5 - dx * 0.5) / dx
        coords = np.stack(np.broadcast_arrays(rows[:, None], cols[None, :]))
        out[r0:r1] += ndimage.map_coordinates(lift, coords, order=3, mode='nearest',
                                              output=np.float32)
    on = (w_geo * w_ridge) > 0.9
    print(f"   till relief on {float(on.mean()) * 100:.1f}% of the playable square, "
          f"rms {float(np.sqrt((lift[on] ** 2).mean())):.2f} m, "
          f"{float(np.abs(lift).max()):.2f} m at most")
    return out


def level_platforms(valle_play):
    """Level the ground under every platform the layout marks in the replicated DEM.

    The playable area of the output is copied from the input PNG, so the platforms
    `grade_pads` levels in `sculpt()` never reach it - this is the one place a pad
    can be applied and survive. The geometry is still the layout's: the rectangle,
    the feather and the drain grade all come off the `town` pad record, and nothing
    here decides where a town is.

    Three things it shares with `grade_pads`, because they are the same operation:

    * **The target is the median of the ground the platform stands on**, not a
      constant, so the town sits on its own hillside instead of being quoted against
      a datum that is a mean and not a height.
    * **It is not dead flat.** `drain_grade` leaves a third of a percent of fall to
      the south, clamped to the platform's own extent - left to run on, the target
      plane keeps climbing past the edge while the ground under it does whatever it
      does, and the feather sized off `dz` grows with distance instead of settling.
    * **The feather widens with the cut**, `max(nominal, 1.5*|dz|/tan(4 deg))`, because
      in a smoothstep the steepest gradient is `1.5*rise/run` and a constant feather
      cuts a step wherever the platform sits deep.

    The work is done in a window round the platform rather than over the whole 8192 m
    square: `rect_sdf` of a 400 m pad over 67 megapixels is 268 MB of float per
    temporary, and the answer is zero everywhere past the feather cap anyway.
    """
    pads = [p for p in ml.pads() if p.get('level')]
    if not pads:
        return valle_play
    out = valle_play.copy()
    tan_bank = math.tan(math.radians(BANK_DEG))
    n = out.shape[0]
    for p in pads:
        cx, cy = p['centre']
        w, h = p['size']
        pad = FEATHER_CAP_M + 2.0
        x0 = max(0, int(math.floor(cx - w / 2.0 - pad)))
        x1 = min(n, int(math.ceil(cx + w / 2.0 + pad)))
        y0 = max(0, int(math.floor(cy - h / 2.0 - pad)))
        y1 = min(n, int(math.ceil(cy + h / 2.0 + pad)))
        if x1 <= x0 or y1 <= y0:
            continue
        # Playable metres of pixel centres, the frame map_layout works in.
        X = (np.arange(x0, x1, dtype=np.float32) + 0.5)[None, :]
        Y = (np.arange(y0, y1, dtype=np.float32) + 0.5)[:, None]
        z = out[y0:y1, x0:x1]
        d = ops.rect_sdf(X, Y, cx - w / 2.0, cy - h / 2.0,
                         cx + w / 2.0, cy + h / 2.0)
        on = d <= 0.0
        if not bool(on.any()):
            continue
        sy = np.clip(cy - Y, -h / 2.0, h / 2.0)
        target = (float(np.median(z[on])) + p['drain_grade'] * sy).astype(np.float32)
        dz = target - z
        feather = np.clip(1.5 * np.abs(dz) / tan_bank, p['feather_m'], FEATHER_CAP_M)
        out[y0:y1, x0:x1] = z + (1.0 - ops.smoothstep(d / feather)) * dz
        print(f"   {p['name']}: {w:.0f} x {h:.0f} m platform levelled to "
              f"{float(np.median(z[on])):.2f} m, cut/fill "
              f"{float(np.abs(dz[on]).max()):.2f} m at worst")
    return out


def sculpt_western_lake(valle_play):
    """Carves the western mountain lake basin into valle_play.

    The lake sits strictly BELOW the surrounding terrain with no elevated border.
    The outer margin where the old mountain foot was raised above the plain is
    restored to the natural plain level (35.0 - 36.0 m).
    Inside the lake, the bed descends over a bank and littoral shelf to a deep
    natural basin with a maximum depth of up to 40 meters (bed down to 1.5 m).
    """
    water_bodies = [w for w in ml.water() if w.get('ring')]
    if not water_bodies:
        return valle_play

    out = valle_play.copy()
    playable_m = int(ml.PLAYABLE_M)

    for w in water_bodies:
        pts = w['ring']
        mask_img = Image.new('L', (playable_m, playable_m), 0)
        draw = ImageDraw.Draw(mask_img)
        draw.polygon(pts, outline=1, fill=1)
        mask = np.array(mask_img, dtype=bool)

        d_in = ndimage.distance_transform_edt(mask)
        d_out = ndimage.distance_transform_edt(~mask)

        # 1. Restore the outside plain: find the clean reference plain height outside the old mountain ramp
        ref_mask = (d_out >= 75) & (d_out <= 85)
        _, (ry, rx) = ndimage.distance_transform_edt(~ref_mask, return_indices=True)
        plain_ref_z = out[ry, rx]

        ramp_width = 80.0
        out_u = np.clip(d_out / ramp_width, 0.0, 1.0)
        out_w = out_u * out_u * (3.0 - 2.0 * out_u)

        outside_restored = np.where(~mask & (d_out < ramp_width),
                                    (1.0 - out_w) * np.minimum(out, plain_ref_z) + out_w * out,
                                    out)

        # 2. Shore bank height from outside_restored
        _, (sy, sx) = ndimage.distance_transform_edt(mask, return_indices=True)
        shore_bank_z = outside_restored[sy, sx]

        water_ws = 35.0

        # Bank slope over 0..20m: from shore_bank_z down to water_ws (35.0m)
        bank_w_m = 20.0
        b_u = np.clip(d_in / bank_w_m, 0.0, 1.0)
        b_w = b_u * b_u * (3.0 - 2.0 * b_u)
        near_shore_z = (1.0 - b_w) * np.maximum(shore_bank_z, water_ws) + b_w * water_ws

        # Bed slope over 20..140m: from water_ws down to deep lake bed
        shelf_m = 120.0
        s_u = np.clip((d_in - bank_w_m) / shelf_m, 0.0, 1.0)
        s_w = s_u * s_u * (3.0 - 2.0 * s_u)

        deep_u = np.clip((d_in - bank_w_m - shelf_m) / (d_in.max() - bank_w_m - shelf_m), 0.0, 1.0)
        deep_w = deep_u * deep_u * (3.0 - 2.0 * deep_u)
        # Deepest bed at 1.5 m (depth up to 40 m from surrounding 41.5m terrain, 33.5 m below water surface)
        target_bed = (water_ws - 20.0) - 13.5 * deep_w

        lake_bed_z = np.where(d_in <= bank_w_m,
                              near_shore_z,
                              (1.0 - s_w) * water_ws + s_w * target_bed)

        out = np.where(mask, lake_bed_z, outside_restored)

    return out


def main():
    t_start = time.time()
    print(f"=== FS25 DEM generator ({CANVAS_M}x{CANVAS_M} m canvas, "
          f"{PLAYABLE_M} m playable) ===")
    print("   ", ml.summary())
    problems = ml.validate()
    if problems:
        print("!! layout problems:")
        for p in problems:
            print("   -", p)
        return 1

    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_dem = os.path.join(_ROOT, 'input', 'valle_bonito.png')
    out_dem = os.path.join(script_dir, "dem_new_12k.png")
    out_stats = os.path.join(script_dir, "terrain_stats.json")
    out_vis = os.path.join(script_dir, "dem_new_visual_12k.png")
    out_detail = os.path.join(script_dir, "dem_new_visual_detail_12k.png")

    # Canvas metres of every working pixel. Pixel j spans [4j, 4j+4) of the canvas and
    # its centre is 4j + 2, offset back into playable metres.
    ax1 = ops.work_axis(WORK_PX, WORK_DX, OFFSET_M)
    X, Y = np.meshgrid(ax1, ax1)

    print(f"1. Till plain about {BASE_ELEV_M:.0f} m ({WORK_PX}x{WORK_PX} working "
          f"grid, {WORK_DX:.0f} m/px)...")
    z = build_base(X, Y)

    print(f"2. Sculpting: water and its valley, {len(ml.pads())} town platforms, "
          f"{len(ml.corridors())} roads and streets, then the rim to "
          f"{ml.RIM_CREST_M:.0f} m...")
    z, wet, built = sculpt(z, X, Y)
    print(f"   {float(wet.mean()) * 100:.2f}% under water, "
          f"{float((built > 0.5).mean()) * 100:.2f}% graded for roads")

    print(f"3. Resampling to {CANVAS_M}x{CANVAS_M} and writing 16-bit centimetres...")
    raw = write_dem(z, built, out_dem)

    if os.path.exists(input_dem):
        print(f"   Replicating playable area from '{input_dem}' with original non-playable border...")
        valle = np.array(Image.open(input_dem))
        raw = valle.copy()

        # The border arrives with the old river's outlets cut through it; the rim is not
        # a rim while anything runs clean through it.
        raw, n_breach = fill_border_trenches(raw)
        print(f"   Closing {n_breach} channel(s) cut through the non-playable border...")
        valle_play = valle[OFFSET_M:OFFSET_M + PLAYABLE_M, OFFSET_M:OFFSET_M + PLAYABLE_M].astype(np.float32) / 100.0

        # Clean town and reservoir area (x in [6850, 8192], y in [800, 2500])
        print("   Cleaning town area and water reservoir in DEM...")
        valle_play = clean_town_and_reservoir_area(valle_play)

        # The till's own relief, before anything is levelled onto it or carved out of
        # it, so the platforms and the lake end up exactly as they would have on ground
        # that now rolls up to them.
        print("   Adding the till's swell and swale...")
        valle_play = roughen_till(valle_play)

        # The platforms, before the lake: a water body carves whatever it meets,
        # so where the two ever overlap the basin wins rather than a flat pan over it.
        print(f"   Levelling {len([p for p in ml.pads() if p.get('level')])} "
              f"platform(s) in DEM...")
        valle_play = level_platforms(valle_play)

        # Sculpt western mountain lake
        print("   Sculpting western mountain lake in DEM...")
        valle_play = sculpt_western_lake(valle_play)

        raw[OFFSET_M:OFFSET_M + PLAYABLE_M, OFFSET_M:OFFSET_M + PLAYABLE_M] = np.rint(valle_play * 100.0).astype(np.uint16)

        # The ridge spans the boundary, so it is run after the playable square is in
        # place and before the apron is blended - and the apron's inner value is read
        # back out of `raw` afterwards, because what it has to come down to is the
        # ground that is there and not the copy `valle_play` was before this.
        raw, ridge = extend_east_ridge(raw)
        if ridge is not None:
            print(f"   Running the eastern ridge out of the map from x = {ridge[0]:.0f} m,"
                  f" {ridge[1]:.0f} m at the deepest...")
            valle_play = (raw[OFFSET_M:OFFSET_M + PLAYABLE_M,
                              OFFSET_M:OFFSET_M + PLAYABLE_M].astype(np.float32) / 100.0)

        ys = np.arange(CANVAS_M)
        xs = np.arange(CANVAS_M)
        dx = np.maximum(0, np.maximum(OFFSET_M - xs, xs - (OFFSET_M + PLAYABLE_M - 1)))
        dy = np.maximum(0, np.maximum(OFFSET_M - ys, ys - (OFFSET_M + PLAYABLE_M - 1)))
        for r0 in range(0, CANVAS_M, BAND_ROWS):
            r1 = r0 + BAND_ROWS
            dy_sub = dy[r0:r1, None]
            dx_sub = dx[None, :]
            d_out = np.sqrt(dx_sub**2 + dy_sub**2)
            apron_mask = (d_out > 0) & (d_out < ml.RIM_APRON_M)
            if apron_mask.any():
                yc = np.clip(ys[r0:r1, None] - OFFSET_M, 0, PLAYABLE_M - 1)
                xc = np.clip(xs[None, :] - OFFSET_M, 0, PLAYABLE_M - 1)
                yc_grid = np.broadcast_to(yc, (BAND_ROWS, CANVAS_M))
                xc_grid = np.broadcast_to(xc, (BAND_ROWS, CANVAS_M))
                z_edge = valle_play[yc_grid[apron_mask], xc_grid[apron_mask]] * 100.0
                z_rim = raw[r0:r1][apron_mask].astype(np.float32)
                u = d_out[apron_mask] / ml.RIM_APRON_M
                w = u * u * (3.0 - 2.0 * u)
                raw[r0:r1][apron_mask] = np.rint((1.0 - w) * z_edge + w * z_rim).astype(np.uint16)

        Image.fromarray(raw).save(out_dem)

    print("4. Publishing terrain_stats.json...")
    play_sub = raw[OFFSET_M:OFFSET_M + PLAYABLE_M, OFFSET_M:OFFSET_M + PLAYABLE_M].astype(np.float32) / 100.0
    k_stat = play_sub.shape[0] // STATS_GRID
    k_down = play_sub.shape[0] // 2048
    play_4m = play_sub.reshape(2048, k_down, 2048, k_down).mean(axis=(1, 3))
    slope_4m = np.tan(np.radians(ops.slope_deg(play_4m, 4.0, baseline_m=40.0)))
    hgt = play_sub.reshape(STATS_GRID, k_stat, STATS_GRID, k_stat).mean(axis=(1, 3))
    k_stat_4m = 2048 // STATS_GRID
    slp = slope_4m.reshape(STATS_GRID, k_stat_4m, STATS_GRID, k_stat_4m).mean(axis=(1, 3))
    rough = np.clip(slp / ROUGH_FULL_SCALE, 0.0, 1.0)
    with open(out_stats, 'w') as fh:
        json.dump({'n': STATS_GRID, 'cell_m': PLAYABLE_M / STATS_GRID,
                   'origin': [0.0, 0.0],
                   'height': [round(float(v), 2) for v in hgt.ravel()],
                   'roughness': [round(float(v), 4) for v in rough.ravel()]}, fh)

    print("5. Figures...")
    draw_figures(raw, out_vis, out_detail)

    lo, hi = raw.min() / 100.0, raw.max() / 100.0
    play = raw[OFFSET_M:OFFSET_M + PLAYABLE_M, OFFSET_M:OFFSET_M + PLAYABLE_M]
    print(f"\n   canvas {lo:.2f} .. {hi:.2f} m, playable "
          f"{play.min() / 100.0:.2f} .. {play.max() / 100.0:.2f} m, "
          f"relief {hi - lo:.2f} m")
    print(f"   [+] {out_dem}")
    print(f"   [+] {out_stats}")
    print(f"   [+] {out_vis}")
    print(f"   [+] {out_detail}")
    print(f"   done in {time.time() - t_start:.1f} s")
    return 0


if __name__ == '__main__':
    sys.exit(main())
