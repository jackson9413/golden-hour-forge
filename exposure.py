"""Exposure planning engine for golden-hour-forge.

Pure Python.  Turns a scene description plus a real date and location into
the camera settings you should actually dial in, the light windows you should
be standing in, the gear you are missing, and a shoot-readiness score.

Conventions used throughout:
  EV100  - exposure value normalised to ISO 100.  EV100 = log2(N^2 / t) - log2(ISO/100)
  t      - shutter time in seconds.  EV100 = log2(N^2 / t) at ISO 100,
           so t = (N^2 / 2^EV100) * (100 / ISO)
"""

from __future__ import annotations

import math

from solar import compute_day, minutes_of_day, solar_position, julian_from_utc
from datetime import datetime, timedelta, timezone


APERTURES = [1.4, 1.8, 2.0, 2.8, 4.0, 5.6, 8.0, 11.0, 16.0, 22.0]
ISO_STEPS = [50, 100, 200, 400, 800, 1600, 3200, 6400, 12800, 25600]

SHUTTER_TABLE = [
    1 / 4000, 1 / 3200, 1 / 2500, 1 / 2000, 1 / 1600, 1 / 1250, 1 / 1000,
    1 / 800, 1 / 640, 1 / 500, 1 / 400, 1 / 320, 1 / 250, 1 / 200, 1 / 160,
    1 / 125, 1 / 100, 1 / 80, 1 / 60, 1 / 50, 1 / 40, 1 / 30, 1 / 25,
    1 / 20, 1 / 15, 1 / 13, 1 / 10, 1 / 8, 1 / 6, 1 / 5, 1 / 4, 1 / 3,
    1 / 2.5, 1 / 2, 1 / 1.6, 1 / 1.3, 1, 2, 4, 8, 15, 30, 60,
]

ND_STOPS = [0, 1, 2, 3, 4, 6, 10, 15, 20]


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def shutter_label(seconds):
    """Human label for a shutter time."""
    if seconds is None:
        return "n/a"
    if seconds >= 120:
        return str(int(round(seconds / 60))) + "m"
    if seconds >= 10:
        return str(int(round(seconds))) + "s"
    if seconds >= 1:
        return str(round(seconds, 1)) + "s"
    if seconds >= 0.3:
        return "1/" + str(int(round(1 / seconds)))
    return "1/" + str(int(round(1 / seconds)))


def standard_shutter(seconds):
    """Snap a shutter time to the nearest real camera value."""
    if not seconds or seconds <= 0:
        return 1 / 125
    return min(SHUTTER_TABLE, key=lambda s: abs(math.log(s) - math.log(seconds)))


def min_to_hhmm(minutes):
    """Format minutes past midnight as HH:MM."""
    if minutes is None:
        return "?"
    minutes = int(round(minutes))
    return "%02d:%02d" % ((minutes // 60) % 24, minutes % 60)


def aperture_label(fnum):
    if fnum < 2:
        return "f/" + ("%.1f" % fnum)
    return "f/" + ("%.1f" % fnum).rstrip("0").rstrip(".")


def ev100_from(aperture, shutter_seconds, iso):
    """Exposure value normalised to ISO 100 for a given exposure."""
    if not shutter_seconds or shutter_seconds <= 0:
        return None
    ev = math.log2((aperture ** 2) / shutter_seconds)
    return ev - math.log2(iso / 100.0)


def shutter_for(ev100, aperture, iso):
    """Shutter time in seconds for a target EV100 at a given aperture and ISO."""
    if ev100 is None:
        return None
    return (aperture ** 2 / (2 ** ev100)) * (100.0 / iso)


def stability_shutter(focal_mm, crop=1.0):
    """Classic handheld rule: shutter at least 1 / (focal length x crop)."""
    eff = max(1.0, float(focal_mm) * float(crop or 1.0))
    return 1.0 / eff


def _pick_iso(iso_needed, iso_max):
    """Smallest standard ISO that is at least iso_needed, clamped to the ceiling."""
    for iso in ISO_STEPS:
        if iso >= iso_needed:
            return min(iso, iso_max)
    return iso_max


def solve_exposure(ev_target, aperture, required_shutter, handheld_rule, tripod,
                   iso_max, focal, semantics="fast", nd_target=None, base_iso=100):
    """Solve for ISO, aperture and shutter that satisfy the shooting constraint.

    Remember the direction of the inequality: a faster shutter speed is a
    SHORTER exposure time.  To freeze motion the exposure must be at most
    required_shutter seconds; a tripod lifts the handheld floor entirely.

    For astro the constraint flips -- a long exposure is the point, so the
    solver targets the 300 rule instead of a minimum speed.
    """
    aperture = min(APERTURES, key=lambda a: abs(a - aperture))
    note = ""
    short_of_target = False

    if nd_target:
        # Long-exposure scene: set a clean unfiltered base exposure and let the
        # ND filter supply the extra time.
        iso = min(base_iso, iso_max)
        t = shutter_for(ev_target, aperture, iso)
        return {"iso": iso, "aperture": aperture, "shutter": t,
                "short_of_target": False,
                "note": "Base exposure set without the filter - the ND adds the time."}

    if semantics == "long":
        t_target = 300.0 / max(14.0, float(focal))
        iso_needed = 100.0 * aperture ** 2 / (2 ** ev_target * t_target)
        if iso_needed > iso_max:
            # The ISO ceiling cannot reach the 300 rule target, so open up.
            n_target = math.sqrt(t_target * (2 ** ev_target) * iso_max / 100.0)
            wider = [a for a in APERTURES if a <= n_target + 1e-9]
            if wider:
                aperture = min(wider, key=lambda a: abs(a - n_target))
            iso = iso_max
        else:
            iso = _pick_iso(iso_needed, iso_max)
        t = shutter_for(ev_target, aperture, iso)
        return {"iso": iso, "aperture": aperture, "shutter": t,
                "short_of_target": False,
                "note": "Astro: targeted the 300 rule (" + shutter_label(t_target) + ")"}

    t_max = required_shutter
    if not tripod:
        t_max = min(t_max, handheld_rule)

    iso_needed = 100.0 * aperture ** 2 / (2 ** ev_target * t_max)
    if iso_needed <= iso_max:
        iso = _pick_iso(iso_needed, iso_max)
    else:
        iso = iso_max
        need = iso_needed / float(iso_max)
        new_n = aperture / math.sqrt(need)
        wider = [a for a in APERTURES if a <= new_n + 1e-9]
        if wider:
            aperture = min(wider, key=lambda a: abs(a - new_n))
        t = shutter_for(ev_target, aperture, iso)
        if t > t_max * 1.05:
            short_of_target = True
            note = ("Cannot reach " + shutter_label(t_max) + " at ISO " + str(iso_max)
                    + " and " + aperture_label(aperture) + ".")
    t = shutter_for(ev_target, aperture, iso)
    return {"iso": iso, "aperture": aperture, "shutter": t,
            "short_of_target": short_of_target, "note": note}


# --------------------------------------------------------------------------
# reference data
# --------------------------------------------------------------------------

SCENES = {
    "golden_hour_portrait": {
        "label": "Golden-hour portrait",
        "category": "portrait",
        "ev_range": [9.0, 13.0],
        "ev_default": 11.5,
        "base_iso": 100,
        "aperture": 2.8,
        "windows": ["golden_hour_morning", "golden_hour_evening"],
        "metering": "Evaluative / Matrix with highlight warning on",
        "focus": "Single-point AF with eye detection, 1/3 of a body in front of the subject",
        "shutter_hint": "1/250 keeps a talking subject sharp",
        "light_base": 90,
        "gear_required": [],
        "gear_optional": ["reflector", "flash"],
        "pitfalls": [
            "The sun drops fast -- a 55 minute window is not 55 minutes of usable light",
            "Metering for the sky blows out the face; expose for the highlights",
            "Sun flare is the shot people came for, but it eats a stop or two",
        ],
        "checklist": [
            "Arrive 30 minutes before the window opens to scout a background",
            "Put the sun behind the subject for rim light, or 45 degrees off for modelling",
            "Shoot with the sun behind YOU for even skin tones, side light for texture",
            "Bracket two exposures when the sky and face differ by more than 3 stops",
            "Watch the horizon: the best colour lasts roughly 10 minutes either side of set",
        ],
    },
    "backlit_portrait": {
        "label": "Backlit / contre-jour portrait",
        "category": "portrait",
        "ev_range": [7.0, 11.0],
        "ev_default": 9.0,
        "base_iso": 100,
        "aperture": 2.8,
        "windows": ["golden_hour_morning", "golden_hour_evening"],
        "metering": "Spot meter on the face, then lift exposure compensation",
        "focus": "Single-point AF on the eye, or back-button focus with a fixed person",
        "shutter_hint": "1/250 for a still subject, 1/500 for movement",
        "light_base": 85,
        "gear_required": [],
        "gear_optional": ["reflector", "flash"],
        "pitfalls": [
            "Spot meter the face, never the background -- otherwise the face is black",
            "Raise the shadow or add fill, the camera cannot recover a blocked face",
            "Shoot wide open and let the background fall away",
        ],
        "checklist": [
            "Meter the face and add +1 to +2 stops of exposure compensation",
            "Use a reflector or fill flash to lift the shadows 2 stops",
            "Frame the flare deliberately or shade the lens with your hand",
            "Shoot a test frame and check the histogram for clipped highlights",
        ],
    },
    "blue_hour_portrait": {
        "label": "Blue-hour portrait",
        "category": "portrait",
        "ev_range": [3.0, 6.5],
        "ev_default": 4.5,
        "base_iso": 400,
        "aperture": 1.8,
        "windows": ["blue_hour_morning", "blue_hour_evening"],
        "metering": "Evaluative, underexpose by -0.3 to +0.7 to keep the blue",
        "focus": "Continuous AF, the light is still moving fast",
        "shutter_hint": "1/125 handheld, 1/60 on a tripod",
        "light_base": 72,
        "gear_required": ["tripod"],
        "gear_optional": ["flash"],
        "pitfalls": [
            "Long exposures need a tripod or the sky streaks",
            "Firmware noise at ISO 3200+ is very visible in blue shadows",
            "Colour goes flat if you auto white balance drifts warm",
        ],
        "checklist": [
            "Fix white balance to 4000-4500K or shoot RAW",
            "Bring a tripod -- 1/30 at f/1.8 still needs support",
            "Add 1-2 stops of fill from a street lamp or flash",
            "Check the frame for colour casts from sodium street lights",
        ],
    },
    "harsh_midday_portrait": {
        "label": "Harsh midday portrait",
        "category": "portrait",
        "ev_range": [14.0, 17.0],
        "ev_default": 15.5,
        "base_iso": 100,
        "aperture": 4.0,
        "windows": [],
        "metering": "Evaluative, dial -0.3 to -0.7 for skin",
        "focus": "Single-point AF, prefer open shade",
        "shutter_hint": "1/500 or faster to hold a sharp face in sun",
        "light_base": 42,
        "gear_required": [],
        "gear_optional": ["reflector", "polarizer"],
        "pitfalls": [
            "Overhead sun carves shadows under the eyes and brow",
            "Bright skin plus bright sky can exceed the sensor's dynamic range",
            "People squint and look uncomfortable",
        ],
        "checklist": [
            "Move into open shade or shoot in the last 90 minutes before sunset",
            "Raise the subject's chin slightly and use a reflector to fill the eye sockets",
            "Underexpose by a third of a stop to protect skin highlights",
            "A polariser cuts glare but costs about a stop of light",
        ],
    },
    "overcast_street": {
        "label": "Overcast street / documentary",
        "category": "street",
        "ev_range": [10.0, 14.0],
        "ev_default": 12.0,
        "base_iso": 400,
        "aperture": 2.8,
        "windows": [],
        "metering": "Evaluative, -0.3 EV keeps the sky from going white",
        "focus": "AF-S single point, or zone for street movement",
        "shutter_hint": "1/250 minimum for walking subjects",
        "light_base": 78,
        "gear_required": [],
        "gear_optional": ["polarizer"],
        "pitfalls": [
            "Flat light kills contrast and separation",
            "Bright overcast skies blow out while faces stay grey",
            "Colour looks dull unless you push contrast or shoot RAW",
        ],
        "checklist": [
            "Look for colour in the scene -- signs, shopfronts, a red door",
            "Find a subject against a darker background for separation",
            "Shoot RAW and add contrast in post, the file is flat not finished",
            "Underexpose slightly so the sky keeps its texture",
        ],
    },
    "indoor_event": {
        "label": "Indoor event / party",
        "category": "event",
        "ev_range": [4.0, 9.0],
        "ev_default": 6.5,
        "base_iso": 1600,
        "aperture": 2.8,
        "windows": [],
        "metering": "Evaluative with ISO auto limit set to your ceiling",
        "focus": "Face/eye detect plus a continuous AF zone",
        "shutter_hint": "1/125 for a static group, 1/250 for mingling",
        "light_base": 52,
        "gear_required": [],
        "gear_optional": ["flash"],
        "pitfalls": [
            "Mixed colour temperatures make skin look green or orange",
            "Auto ISO climbs past the ceiling and the noise floor shows",
            "Falling behind on the dance floor loses the moment",
        ],
        "checklist": [
            "Set an ISO ceiling so auto ISO cannot run away",
            "Use bounce flash off the ceiling to soften hard ceiling lights",
            "Shoot wide open wide and crop in, or bring a 35mm",
            "Get a second angle before the room settles into one pose",
        ],
    },
    "night_street": {
        "label": "Night street / neon",
        "category": "street",
        "ev_range": [3.0, 8.0],
        "ev_default": 5.5,
        "base_iso": 3200,
        "aperture": 1.8,
        "windows": [],
        "metering": "Evaluative, -0.3 to -0.7 EV to keep neon from clipping",
        "focus": "AF-S single point, or manual focus at f/8 and deeper",
        "shutter_hint": "1/60 handheld on a steady hand, 1/8 on a tripod",
        "light_base": 38,
        "gear_required": [],
        "gear_optional": ["tripod"],
        "pitfalls": [
            "Handheld at 1/30 shakes before you notice",
            "Bright signs clip to white blobs",
            "Mixed sodium and LED lighting fights auto white balance",
        ],
        "checklist": [
            "Brace the camera against a post or use a tripod at 1/8",
            "Shoot RAW and correct the colour separately from the exposure",
            "Look for wet pavement and reflections, that is the light",
            "Set the shutter to 1/60 if you are shooting people, 2s if you are shooting empty streets",
        ],
    },
    "sports_action": {
        "label": "Sports / action",
        "category": "action",
        "ev_range": [12.0, 16.0],
        "ev_default": 14.0,
        "base_iso": 800,
        "aperture": 4.0,
        "windows": [],
        "metering": "Evaluative with sports matrix, +0.3 to +0.7 EV",
        "focus": "Continuous AF with a wide zone, subject tracking",
        "shutter_hint": "1/1000 or faster, 1/1600 for fast ball games",
        "light_base": 62,
        "gear_required": [],
        "gear_optional": [],
        "pitfalls": [
            "Focus that does not track costs more shots than slow shutter",
            "Faster shutter means higher ISO and more noise",
            "Sideline shade and sunny field can be 4 stops apart",
        ],
        "checklist": [
            "Shoot burst and pick the frame after the fact",
            "Pre-focus on the spot the play will happen, not the current action",
            "1/1000 at f/4 keeps the ball sharp and the background soft",
            "Watch the sun side of the field -- the exposure changes every inning",
        ],
    },
    "wildlife": {
        "label": "Wildlife / nature",
        "category": "nature",
        "ev_range": [12.0, 16.0],
        "ev_default": 14.0,
        "base_iso": 1600,
        "aperture": 5.6,
        "windows": [],
        "metering": "Evaluative, -0.3 EV on bright fur or water",
        "focus": "Single-point or animal eye detect with continuous AF",
        "shutter_hint": "1/1600 for birds, 1/500 for large mammals",
        "light_base": 60,
        "gear_required": [],
        "gear_optional": ["tripod"],
        "pitfalls": [
            "Long lenses need far more shutter speed than people expect",
            "Heat haze at midday ruins long-lens detail",
            "Focus often lands on the wrong branch",
        ],
        "checklist": [
            "Early morning or last hour of light for active animals and softer backgrounds",
            "Keep the shutter above 1/1000 for birds in flight",
            "Support the long lens on a monopod or beanbag",
            "Pre-focus on the spot the animal will use",
        ],
    },
    "landscape_wide": {
        "label": "Landscape / wide vista",
        "category": "landscape",
        "ev_range": [10.0, 15.0],
        "ev_default": 12.5,
        "base_iso": 100,
        "aperture": 8.0,
        "windows": ["golden_hour_morning", "golden_hour_evening"],
        "metering": "Evaluative, or manual with the histogram",
        "focus": "Manual focus at hyperfocal, or focus at the hyperfocal distance",
        "shutter_hint": "1/125 handheld, 1/4 on a tripod for foreground blur",
        "light_base": 82,
        "gear_required": [],
        "gear_optional": ["tripod", "polarizer", "nd"],
        "pitfalls": [
            "Foreground blur needs a long exposure and therefore a tripod",
            "Dynamic range between sky and foreground exceeds many sensors",
            "Harsh midday light flattens the land",
        ],
        "checklist": [
            "Compute the hyperfocal distance and focus there for front-to-back sharpness",
            "Bracket 3 exposures for skies that are brighter than the land",
            "Polariser for glare on water and rocks, ND for a slower shutter",
            "Use the golden hour windows for side light and long shadows",
        ],
    },
    "long_exposure": {
        "label": "Long exposure / water silky",
        "category": "landscape",
        "ev_range": [8.0, 13.0],
        "ev_default": 10.0,
        "base_iso": 100,
        "aperture": 8.0,
        "nd_target_seconds": 8.0,
        "windows": [],
        "metering": "Manual -- you are choosing the shutter, not the camera",
        "focus": "Manual focus with a tripod, then recompose if needed",
        "shutter_hint": "4s to 60s for silky water",
        "light_base": 78,
        "gear_required": ["tripod", "nd"],
        "gear_optional": [],
        "pitfalls": [
            "Without an ND filter you lose the shutter speed in daylight",
            "Wind moves the frame and creates ghosting",
            "Bright water plus long exposure needs careful highlight control",
        ],
        "checklist": [
            "Mount the camera, focus manually, and cover the viewfinder for long exposures",
            "Use a 2-10 stop ND in daylight, stack filters carefully",
            "Shoot 5-10 second frames and stack them for clean water",
            "Turn on long exposure noise reduction or shoot RAW",
        ],
    },
    "macro": {
        "label": "Macro / close-up",
        "category": "closeup",
        "ev_range": [8.0, 13.0],
        "ev_default": 10.5,
        "base_iso": 400,
        "aperture": 5.6,
        "windows": [],
        "metering": "Spot or evaluative, -0.3 EV on bright subjects",
        "focus": "Manual or single-point with focus stacking for depth",
        "shutter_hint": "1/250 handheld, or 1/8 with a tripod and focus stack",
        "light_base": 68,
        "gear_required": [],
        "gear_optional": ["tripod", "diffuser"],
        "pitfalls": [
            "Macro depth of field is thin even at f/8",
            "Wind moves a subject at 20cm",
            "Direct flash flattens texture",
        ],
        "checklist": [
            "Focus stack 8-15 frames for full depth at macro distances",
            "Diffuse the light, a small diffuser beats direct flash",
            "Use a lens hood and a hand to block stray light",
            "Shoot in soft light to avoid specular hotspots",
        ],
    },
    "food": {
        "label": "Food / tabletop",
        "category": "studio",
        "ev_range": [6.0, 11.0],
        "ev_default": 8.5,
        "base_iso": 200,
        "aperture": 4.0,
        "windows": [],
        "metering": "Spot meter on the hero ingredient",
        "focus": "Manual or single-point on the front edge of the plate",
        "shutter_hint": "1/125 on a tripod, 1/60 handheld",
        "light_base": 72,
        "gear_required": [],
        "gear_optional": ["reflector", "flash"],
        "pitfalls": [
            "Mixed colour temperature from the room lights ruins food colour",
            "Too shallow a depth of field hides the dish",
            "Steam disappears in 2 minutes, shoot fast",
        ],
        "checklist": [
            "Use one light source and a white card opposite it",
            "Shoot slightly off the axis so the plate is not dead centre",
            "Get the camera low, level with the food",
            "Shoot the build too -- the hands make the shot",
        ],
    },
    "concert_stage": {
        "label": "Concert / stage light",
        "category": "event",
        "ev_range": [7.0, 13.0],
        "ev_default": 10.0,
        "base_iso": 3200,
        "aperture": 2.8,
        "windows": [],
        "metering": "Evaluative, spot meter for the key light",
        "focus": "Continuous AF, or manual focus on the performer",
        "shutter_hint": "1/250 for a performer on stage",
        "light_base": 45,
        "gear_required": [],
        "gear_optional": [],
        "pitfalls": [
            "Stage lighting changes by a stop between songs",
            "Clipping coloured stage wash is unavoidable",
            "Crowd silhouettes block the frame",
        ],
        "checklist": [
            "Check your ISO ceiling against the venue rules before the show",
            "Shoot wide and crop later",
            "Watch the pit for hands that block the light",
            "Lock focus on the performer during the dark passages",
        ],
    },
    "astro": {
        "label": "Astro / night sky",
        "category": "landscape",
        "ev_range": [-9.0, -3.0],
        "ev_default": -7.0,
        "base_iso": 1600,
        "aperture": 2.8,
        "windows": [],
        "metering": "Manual -- fixed settings, stack the frames",
        "focus": "Manual focus at infinity with a bright star or a magnified live view",
        "shutter_hint": "15s at f/2.8, 300 rule",
        "light_base": 40,
        "gear_required": ["tripod"],
        "gear_optional": ["nd"],
        "pitfalls": [
            "Light pollution and a bright moon kill contrast",
            "Camera sensors need multiple dark frames for noise reduction",
            "A tracking mount changes the whole equation",
        ],
        "checklist": [
            "Find the darkest spot with a light pollution map",
            "Check the moon phase and illumination before you drive out",
            "Use the 300 rule: 300 divided by focal length for the maximum shutter",
            "Shoot 15 dark frames for stacking and keep the camera at one temperature",
        ],
    },
}


LIGHT_CONDITIONS = {
    "golden": {
        "label": "Golden / low warm sun",
        "ev_delta": 0.0,
        "light_score": 94,
        "hardness": 35,
        "headroom": 72,
        "colour": "warm 3000-4200K",
    },
    "sunlit": {
        "label": "Direct sun",
        "ev_delta": 1.0,
        "light_score": 72,
        "hardness": 80,
        "headroom": 55,
        "colour": "neutral 5200-5600K",
    },
    "harsh": {
        "label": "Harsh midday sun",
        "ev_delta": 2.5,
        "light_score": 40,
        "hardness": 96,
        "headroom": 32,
        "colour": "neutral 5500K",
    },
    "overcast": {
        "label": "Overcast / soft",
        "ev_delta": 1.5,
        "light_score": 76,
        "hardness": 18,
        "headroom": 84,
        "colour": "cool 6200-7000K",
    },
    "backlit": {
        "label": "Backlit / sun behind subject",
        "ev_delta": -1.5,
        "light_score": 86,
        "hardness": 45,
        "headroom": 28,
        "colour": "warm with flare",
    },
    "blue_hour": {
        "label": "Blue hour",
        "ev_delta": -2.5,
        "light_score": 70,
        "hardness": 12,
        "headroom": 88,
        "colour": "cool 7000-9000K",
    },
    "indoor": {
        "label": "Indoor mixed / tungsten",
        "ev_delta": -1.0,
        "light_score": 50,
        "hardness": 55,
        "headroom": 60,
        "colour": "mixed 3000-4500K",
    },
    "night": {
        "label": "Night / artificial only",
        "ev_delta": -1.0,
        "light_score": 34,
        "hardness": 40,
        "headroom": 62,
        "colour": "mixed neon",
    },
    "snow": {
        "label": "Snow / bright reflective",
        "ev_delta": 2.0,
        "light_score": 80,
        "hardness": 70,
        "headroom": 25,
        "colour": "neutral 5600K",
    },
    "fog": {
        "label": "Fog / mist",
        "ev_delta": 1.0,
        "light_score": 58,
        "hardness": 8,
        "headroom": 78,
        "colour": "flat neutral",
    },
}


MOVEMENTS = {
    "static": {"label": "Still / static subject", "shutter": 1 / 125, "semantics": "fast"},
    "portrait_breathing": {"label": "Portrait (breathing)", "shutter": 1 / 250, "semantics": "fast"},
    "walking": {"label": "Walking", "shutter": 1 / 250, "semantics": "fast"},
    "children": {"label": "Children / pets playing", "shutter": 1 / 500, "semantics": "fast"},
    "sports": {"label": "Fast sport / ball", "shutter": 1 / 1000, "semantics": "fast"},
    "traffic": {"label": "Moving traffic / vehicles", "shutter": 1 / 500, "semantics": "fast"},
    "water": {"label": "Water flow (intentional blur)", "shutter": 1 / 30, "semantics": "fast"},
    "crowd": {"label": "Crowd / people mixing", "shutter": 1 / 250, "semantics": "fast"},
    "stars": {"label": "Stars / astro", "shutter": 15.0, "semantics": "long"},
}


GEAR_LABELS = {
    "tripod": "Tripod",
    "nd": "ND filter",
    "flash": "Flash",
    "reflector": "Reflector",
    "polarizer": "Polariser",
    "diffuser": "Diffuser",
}


CITIES = [
    {"name": "Chicago", "lat": 41.8781, "lon": -87.6298, "tz": "America/Chicago"},
    {"name": "New York", "lat": 40.7128, "lon": -74.0060, "tz": "America/New_York"},
    {"name": "Los Angeles", "lat": 34.0522, "lon": -118.2437, "tz": "America/Los_Angeles"},
    {"name": "San Francisco", "lat": 37.7749, "lon": -122.4194, "tz": "America/Los_Angeles"},
    {"name": "Seattle", "lat": 47.6062, "lon": -122.3321, "tz": "America/Los_Angeles"},
    {"name": "Denver", "lat": 39.7392, "lon": -104.9903, "tz": "America/Denver"},
    {"name": "Austin", "lat": 30.2672, "lon": -97.7431, "tz": "America/Chicago"},
    {"name": "Houston", "lat": 29.7604, "lon": -95.3698, "tz": "America/Chicago"},
    {"name": "Phoenix", "lat": 33.4484, "lon": -112.0740, "tz": "America/Phoenix"},
    {"name": "Dallas", "lat": 32.7767, "lon": -96.7970, "tz": "America/Chicago"},
    {"name": "Minneapolis", "lat": 44.9778, "lon": -93.2650, "tz": "America/Chicago"},
    {"name": "Atlanta", "lat": 33.7490, "lon": -84.3880, "tz": "America/New_York"},
    {"name": "Miami", "lat": 25.7617, "lon": -80.1918, "tz": "America/New_York"},
    {"name": "Boston", "lat": 42.3601, "lon": -71.0589, "tz": "America/New_York"},
    {"name": "Washington DC", "lat": 38.9072, "lon": -77.0369, "tz": "America/New_York"},
    {"name": "Philadelphia", "lat": 39.9526, "lon": -75.1652, "tz": "America/New_York"},
    {"name": "Toronto", "lat": 43.6532, "lon": -79.3832, "tz": "America/Toronto"},
    {"name": "Vancouver", "lat": 49.2827, "lon": -123.1207, "tz": "America/Vancouver"},
    {"name": "London", "lat": 51.5074, "lon": -0.1278, "tz": "Europe/London"},
    {"name": "Paris", "lat": 48.8566, "lon": 2.3522, "tz": "Europe/Paris"},
    {"name": "Berlin", "lat": 52.5200, "lon": 13.4050, "tz": "Europe/Berlin"},
    {"name": "Madrid", "lat": 40.4168, "lon": -3.7038, "tz": "Europe/Madrid"},
    {"name": "Rome", "lat": 41.9028, "lon": 12.4964, "tz": "Europe/Rome"},
    {"name": "Amsterdam", "lat": 52.3676, "lon": 4.9041, "tz": "Europe/Amsterdam"},
    {"name": "Copenhagen", "lat": 55.6761, "lon": 12.5683, "tz": "Europe/Copenhagen"},
    {"name": "Stockholm", "lat": 59.3293, "lon": 18.0686, "tz": "Europe/Stockholm"},
    {"name": "Lisbon", "lat": 38.7223, "lon": -9.1393, "tz": "Europe/Lisbon"},
    {"name": "Tokyo", "lat": 35.6762, "lon": 139.6503, "tz": "Asia/Tokyo"},
    {"name": "Osaka", "lat": 34.6937, "lon": 135.5023, "tz": "Asia/Tokyo"},
    {"name": "Seoul", "lat": 37.5665, "lon": 126.9780, "tz": "Asia/Seoul"},
    {"name": "Singapore", "lat": 1.3521, "lon": 103.8198, "tz": "Asia/Singapore"},
    {"name": "Bangkok", "lat": 13.7563, "lon": 100.5018, "tz": "Asia/Bangkok"},
    {"name": "Sydney", "lat": -33.8688, "lon": 151.2093, "tz": "Australia/Sydney"},
    {"name": "Melbourne", "lat": -37.8136, "lon": 144.9631, "tz": "Australia/Melbourne"},
    {"name": "Auckland", "lat": -36.8485, "lon": 174.7633, "tz": "Pacific/Auckland"},
    {"name": "Dubai", "lat": 25.2048, "lon": 55.2708, "tz": "Asia/Dubai"},
    {"name": "Mumbai", "lat": 19.0760, "lon": 72.8777, "tz": "Asia/Kolkata"},
    {"name": "Delhi", "lat": 28.6139, "lon": 77.2090, "tz": "Asia/Kolkata"},
    {"name": "Cape Town", "lat": -33.9249, "lon": 18.4241, "tz": "Africa/Johannesburg"},
    {"name": "Reykjavik", "lat": 64.1466, "lon": -21.9426, "tz": "Atlantic/Reykjavik"},
    {"name": "Tromso", "lat": 69.6492, "lon": 18.9553, "tz": "Europe/Oslo"},
    {"name": "Honolulu", "lat": 21.3069, "lon": -157.8583, "tz": "Pacific/Honolulu"},
    {"name": "Anchorage", "lat": 61.2181, "lon": -149.9003, "tz": "America/Anchorage"},
]


VERDICT_BANDS = [
    (85, "shoot_ready", "Shoot ready"),
    (70, "mostly_ready", "Mostly ready"),
    (55, "needs_setup", "Needs setup"),
    (40, "tight_but_usable", "Tight but usable"),
    (0, "needs_rework", "Needs rework"),
]


def verdict_for(score):
    for threshold, key, label in VERDICT_BANDS:
        if score >= threshold:
            return key, label
    return "needs_rework", "Needs rework"


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------

def _clamp(value, low, high):
    return max(low, min(high, value))


def _azimuth_name(az):
    names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return names[int(((az % 360) + 11.25) % 360 // 22.5)]


def _solar_at(day_info, minutes):
    """Sun altitude and azimuth at a given minute of the local day."""
    offset_hours = 0.0
    tz_name = day_info.get("timezone")
    try:
        from solar import tz_offset_hours
        day = datetime.strptime(day_info["date"], "%Y-%m-%d").date()
        offset_hours = tz_offset_hours(day, tz_name)
    except Exception:
        pass
    dt_utc = datetime.strptime(day_info["date"], "%Y-%m-%d").replace(
        tzinfo=timezone.utc) - timedelta(hours=offset_hours) + timedelta(minutes=minutes)
    alt, az = solar_position(julian_from_utc(dt_utc), day_info["lat"], day_info["lon"])
    return alt, az


def _window_minutes(day_info, key):
    block = day_info.get(key) or {}
    if not block.get("start"):
        return None
    start = minutes_of_day(block["start"][11:16])
    end = minutes_of_day(block["end"][11:16])
    if start is None or end is None:
        return None
    return start, end


def analyze(payload):
    """Run the full analysis for one shoot plan."""
    payload = payload or {}
    scene_key = payload.get("scene") if payload.get("scene") in SCENES else "golden_hour_portrait"
    scene = SCENES[scene_key]
    cond_key = payload.get("light_condition") if payload.get("light_condition") in LIGHT_CONDITIONS else "golden"
    cond = LIGHT_CONDITIONS[cond_key]
    move_key = payload.get("subject") if payload.get("subject") in MOVEMENTS else "static"
    movement = MOVEMENTS[move_key]

    lat = float(payload.get("lat", 41.8781))
    lon = float(payload.get("lon", -87.6298))
    tz_name = payload.get("tz") or "America/Chicago"
    date_str = payload.get("date") or datetime.now().strftime("%Y-%m-%d")
    day_info = compute_day(date_str, lat, lon, tz_name)

    shoot_time = payload.get("shoot_time") or ""
    shoot_min = minutes_of_day(shoot_time)
    if shoot_min is None:
        sunset_min = minutes_of_day((day_info.get("sunset") or "00:00")[11:16])
        shoot_min = sunset_min - 45 if sunset_min else 1020

    focal = float(payload.get("focal_length") or 50)
    crop = float(payload.get("crop") or 1.0)
    iso_max = int(payload.get("iso_max") or 3200)
    gear_in = payload.get("gear") or {}
    gear = {k: bool(gear_in.get(k)) for k in GEAR_LABELS}

    # ---- target exposure value -------------------------------------------
    ev_target = scene["ev_default"] + cond["ev_delta"]
    ev_target = _clamp(ev_target, scene["ev_range"][0], scene["ev_range"][1])

    aperture = float(payload.get("aperture") or scene["aperture"])
    aperture = min(APERTURES, key=lambda a: abs(a - aperture))

    required_shutter = movement["shutter"]
    handheld_rule = stability_shutter(focal, crop)
    has_tripod = bool(gear.get("tripod"))
    semantics = movement.get("semantics", "fast")
    if scene_key == "astro":
        semantics = "long"

    nd_target = scene.get("nd_target_seconds")
    solved = solve_exposure(ev_target, aperture, required_shutter, handheld_rule,
                             has_tripod, iso_max, focal, semantics,
                             nd_target=nd_target, base_iso=scene["base_iso"])
    chosen_iso = solved["iso"]
    aperture = solved["aperture"]
    chosen_shutter = solved["shutter"]
    short_of_target = solved["short_of_target"]
    snapped_shutter = standard_shutter(chosen_shutter)
    ev_check = ev100_from(aperture, snapped_shutter, chosen_iso)

    # ---- aperture ladder -------------------------------------------------
    ladder = []
    idx = APERTURES.index(aperture)
    ladder_apertures = [APERTURES[i] for i in range(max(0, idx - 2), min(len(APERTURES), idx + 3))]
    base_iso = scene["base_iso"]
    for fnum in ladder_apertures:
        base_t = standard_shutter(shutter_for(ev_target, fnum, base_iso))
        iso_1600_t = standard_shutter(shutter_for(ev_target, fnum, 1600))
        chosen_t = standard_shutter(shutter_for(ev_target, fnum, chosen_iso))
        ladder.append({
            "aperture": aperture_label(fnum),
            "shutter_at_base_iso": shutter_label(base_t),
            "iso_used": base_iso,
            "shutter_at_iso1600": shutter_label(iso_1600_t),
            "shutter_at_chosen_iso": shutter_label(chosen_t),
            "iso_chosen": chosen_iso,
        })

    # ---- ND filter table -------------------------------------------------
    nd_table = []
    base_t = chosen_shutter
    nd_target = scene.get("nd_target_seconds") or 8.0
    recommended_nd = None
    for stops in ND_STOPS:
        factor = 2 ** stops
        t = base_t * factor
        nd_table.append({
            "stops": stops,
            "filter": ("none" if stops == 0 else str(stops) + "-stop ND"),
            "shutter": shutter_label(standard_shutter(t)),
            "seconds": round(t, 3),
            "needs_tripod": bool(t >= 0.5),
        })
    if base_t > 0:
        candidates = [row for row in nd_table if 0 < row["seconds"] <= 120]
        if candidates:
            recommended_nd = min(candidates, key=lambda row: abs(row["seconds"] - nd_target))

    # ---- timing ----------------------------------------------------------
    ideal_windows = []
    for key in scene["windows"]:
        win = _window_minutes(day_info, key)
        if win:
            ideal_windows.append((key, win))
    session = 90
    session_start = shoot_min - session / 2
    session_end = shoot_min + session / 2

    overlap = 0.0
    for _key, (w_start, w_end) in ideal_windows:
        lo = max(session_start, w_start)
        hi = min(session_end, w_end)
        if hi > lo:
            overlap += (hi - lo)
    overlap_ratio = min(1.0, overlap / float(session)) if session else 0.0

    in_window = False
    for _key, (w_start, w_end) in ideal_windows:
        if w_start <= shoot_min <= w_end:
            in_window = True

    # ---- sun position advice --------------------------------------------
    sun_alt, sun_az = _solar_at(day_info, shoot_min)
    if sun_alt > 3:
        if cond_key == "backlit":
            sun_advice = ("Sun is at " + str(int(sun_az)) + " deg (" + _azimuth_name(sun_az)
                          + "). The subject is between you and the sun: meter the face and add fill.")
        elif sun_alt > 25:
            sun_advice = ("Sun is high at " + str(int(sun_alt)) + " deg and "
                          + _azimuth_name(sun_az) + " of you. Harsh overhead light -- find open shade.")
        else:
            sun_advice = ("Sun is low at " + str(int(sun_alt)) + " deg, "
                          + _azimuth_name(sun_az) + ". Stand with it over your shoulder for even light, "
                          "or have your subject face it for rim light and flare.")
    elif sun_alt > -6:
        sun_advice = ("Sun is at " + str(int(sun_alt)) + " deg (" + _azimuth_name(sun_az)
                      + "): civil twilight. Ambient light only, no sun to work with.")
    else:
        sun_advice = ("Sun is " + str(int(abs(sun_alt))) + " deg below the horizon at "
                      + _azimuth_name(sun_az) + ". Artificial light and long exposures only.")

    # ---- findings --------------------------------------------------------
    flags = []

    def flag(code, severity, title, evidence, fix):
        flags.append({"code": code, "severity": severity, "title": title,
                      "evidence": evidence, "fix": fix})

    if day_info.get("polar") == "polar_day":
        flag("polar_day", "medium", "The sun never sets on this date here",
             "Polar day at " + str(lat) + " deg latitude.",
             "Shoot the low-angle light that never quite arrives, or pick another date.")
    if day_info.get("polar") == "polar_night":
        flag("polar_night", "medium", "The sun never rises on this date here",
             "Polar night at " + str(lat) + " deg latitude.",
             "Plan for aurora, moonlight or a studio-style setup instead.")
    if scene["windows"] and not ideal_windows:
        flag("no_ideal_window", "high", "No usable light window on this date",
             "No " + ", ".join(scene["windows"]).replace("_", " ") + " window exists at this latitude.",
             "Move to a different date, a different latitude, or change the scene.")

    if scene["windows"] and ideal_windows and not in_window:
        best = min(
            ideal_windows,
            key=lambda w: min(abs(shoot_min - w[1][0]), abs(shoot_min - w[1][1])))
        offset_txt = "morning" if "morning" in best[0] else "evening"
        flag("outside_window", "high", "Your shoot time is outside the good window",
             "Shoot at " + shoot_time + " but the " + offset_txt + " window is "
             + min_to_hhmm(best[1][0]) + " and runs to " + min_to_hhmm(best[1][1]) + ".",
             "Shift to " + min_to_hhmm(best[1][0]) + " or move to the next day.")

    if cond_key == "harsh":
        flag("harsh_light", "high", "Harsh overhead light",
             "Sun altitude around " + str(int(max(0, sun_alt))) + " deg with hard shadows.",
             "Move to open shade, shoot within 90 minutes of sunset, or wait for cloud cover.")
    if cond_key == "backlit":
        flag("backlit_fill", "high", "Backlight needs fill",
             "Subject lit from behind, so the face sits 2-4 stops under the sky.",
             "Add a reflector or fill flash, or meter the face and lift shadows in post.")
    if cond_key == "blue_hour":
        flag("blue_hour_support", "medium", "Blue hour needs support",
             "Light level around EV100 " + ("%.1f" % ev_target) + ".",
             "Bring a tripod or brace the camera; 1/30 handheld will shake.")
    if cond_key == "indoor" or cond_key == "night":
        flag("white_balance_mix", "medium", "Mixed colour temperature",
             cond["colour"] + " lighting.",
             "Shoot RAW and set a custom white balance, or use a gel on the flash.")
    if cond_key == "snow":
        flag("snow_overexpose", "medium", "Bright reflective surface",
             "Snow can read 1-2 stops brighter than it looks.",
             "Meter for the brightest snow and check the histogram for clipped highlights.")
    if cond_key == "fog":
        flag("fog_contrast", "medium", "Fog kills contrast",
             "Veil in the air flattens the whole frame.",
             "Shoot a subject close to camera against a distant layer for separation.")

    if snapped_shutter > handheld_rule and not has_tripod:
        flag("handheld_risk", "high", "Handheld shake likely",
             "At " + aperture_label(aperture) + " and " + shutter_label(snapped_shutter)
             + " with a " + str(int(focal)) + "mm lens, you need about "
             + shutter_label(handheld_rule) + " or faster.",
             "Add a tripod, raise the ISO, or open the aperture one stop.")

    if semantics == "fast" and not nd_target and snapped_shutter > required_shutter * 1.05:
        flag("motion_blur", "high", "Subject will blur",
             "Movement needs " + shutter_label(required_shutter) + " but you have "
             + shutter_label(snapped_shutter) + ".",
             "Raise ISO to " + str(min(iso_max, chosen_iso * 2)) + " or open the aperture, "
             "then accept the noise.")

    if semantics == "long" and snapped_shutter < 4:
        flag("astro_short", "medium", "Too short for astro",
             "At " + shutter_label(snapped_shutter) + " the stars barely move between frames.",
             "Aim for 15-25 seconds at f/2.8 or wider, or mount a tracking head.")

    if short_of_target:
        flag("cannot_reach_shutter", "high", "Cannot reach the shutter speed you need",
             solved["note"],
             "Raise the ISO ceiling, open the aperture, use the tripod, "
             "or move to a brighter time of day.")

    if chosen_iso >= 6400:
        flag("high_iso", "medium", "High ISO noise",
             "ISO " + str(chosen_iso) + " is above a comfortable noise floor.",
             "Look for one more stop of light, use an ND filter in daylight, or accept softness.")
    elif short_of_target:
        flag("iso_ceiling", "high", "ISO ceiling reached",
             "You need more than ISO " + str(iso_max) + " for this scene.",
             "Raise the ceiling, add light, or change the scene to a time of day with more light.")

    for item in scene["gear_required"]:
        if not gear.get(item):
            flag("missing_gear_" + item, "high", "Missing gear: " + GEAR_LABELS[item],
                 "This scene needs a " + GEAR_LABELS[item].lower() + " to work as planned.",
                 "Bring a " + GEAR_LABELS[item].lower() + ", or pick a scene that does not need one.")

    if scene["gear_required"] and "nd" in scene["gear_required"] and not gear.get("nd"):
        pass
    if scene_key == "long_exposure" and not gear.get("nd"):
        flag("nd_needed", "high", "No ND filter for daylight long exposure",
             "Without a filter you cannot reach 4s or slower in daylight.",
             "Use at least a 6-stop ND, or shoot the long exposure at blue hour.")

    if scene_key == "astro":
        moon = day_info.get("moon") or {}
        if moon.get("illumination_pct", 0) > 60:
            flag("moon_bright", "medium", "Bright moon washes out the sky",
                 "Moon is " + str(moon.get("illumination_pct")) + "% lit (" + moon.get("phase", "") + ").",
                 "Shoot a few days either side of full moon, or frame the moon itself.")
        if not gear.get("tripod"):
            flag("missing_gear_tripod", "high", "Missing gear: Tripod",
                 "Astro needs a locked camera for 15 second frames.",
                 "Bring a tripod.")

    if scene_key == "golden_hour_portrait" and cond_key == "golden" and in_window:
        gh_len = (day_info["golden_hour_evening"].get("minutes")
                  or day_info["golden_hour_morning"].get("minutes"))
        flag("window_closing", "medium", "The good light is short",
             "Golden hour at this latitude and date runs about "
             + str(gh_len if gh_len else "?") + " minutes.",
             "Be set up and framed before the window opens, not after it starts.")

    # ---- scoring ---------------------------------------------------------
    light_score = _clamp(scene["light_base"] * 0.45 + cond["light_score"] * 0.55, 0, 100)
    if in_window:
        light_score += 6
    else:
        light_score -= 14
    light_score = _clamp(light_score, 0, 100)

    if day_info.get("polar") in ("polar_day", "polar_night"):
        timing_score = 25
    elif not ideal_windows:
        timing_score = 62 if scene["windows"] else 70
    else:
        timing_score = _clamp(40 + 60 * overlap_ratio, 0, 100)

    stability = 100.0
    if semantics == "fast" and not nd_target and snapped_shutter > required_shutter:
        stability -= min(45, (snapped_shutter / max(required_shutter, 1e-6) - 1) * 22)
    if snapped_shutter > handheld_rule and not has_tripod:
        stability -= min(35, (snapped_shutter / max(handheld_rule, 1e-6) - 1) * 18)
    if chosen_iso >= 3200:
        stability -= 8
    if chosen_iso >= 6400:
        stability -= 12
    stability_score = _clamp(stability, 0, 100)

    gear_score = 100.0
    for item in scene["gear_required"]:
        if not gear.get(item):
            gear_score -= 30
    for item in scene["gear_optional"]:
        if not gear.get(item):
            gear_score -= 5
    if scene_key == "long_exposure" and not gear.get("nd"):
        gear_score -= 20
    gear_score = _clamp(gear_score, 0, 100)

    headroom = cond["headroom"]
    if scene_key in ("backlit_portrait", "sports_action") and cond_key == "harsh":
        headroom -= 10
    if gear.get("flash") and cond_key in ("backlit", "indoor", "night"):
        headroom += 10
    headroom_score = _clamp(headroom, 0, 100)

    weights = {"light": 0.28, "timing": 0.22, "stability": 0.20,
               "gear": 0.15, "headroom": 0.15}
    if scene["category"] == "action":
        weights = {"light": 0.20, "timing": 0.15, "stability": 0.35,
                   "gear": 0.15, "headroom": 0.15}
    elif scene["category"] == "landscape":
        weights = {"light": 0.32, "timing": 0.26, "stability": 0.18,
                   "gear": 0.14, "headroom": 0.10}
    elif scene["category"] == "event":
        weights = {"light": 0.18, "timing": 0.14, "stability": 0.28,
                   "gear": 0.18, "headroom": 0.22}

    axes = {
        "light": round(light_score, 1),
        "timing": round(timing_score, 1),
        "stability": round(stability_score, 1),
        "gear": round(gear_score, 1),
        "headroom": round(headroom_score, 1),
    }
    score = sum(axes[k] * weights[k] for k in axes)
    score = round(_clamp(score, 0, 100), 1)
    verdict_key, verdict_label = verdict_for(score)

    severity_penalty = sum({"high": 5, "medium": 2.5, "low": 1}.get(f["severity"], 0)
                           for f in flags)
    score = round(_clamp(score - min(12, severity_penalty * 0.5), 0, 100), 1)
    verdict_key, verdict_label = verdict_for(score)

    # ---- checklist -------------------------------------------------------
    checklist = list(scene["checklist"])
    if ideal_windows:
        for key, (w_start, w_end) in ideal_windows:
            label = key.replace("_", " ").title()
            mins = w_end - w_start
            checklist.append("Book the " + label + " window (" + min_to_hhmm(w_start)
                             + " to " + min_to_hhmm(w_end) + ", about " + str(int(mins)) + " minutes)")
    if not gear.get("tripod"):
        checklist.append("Bring a tripod -- or plan every frame handheld at a faster shutter")
    checklist.append("Set white balance to " + cond["colour"].split()[0]
                     + " instead of leaving it on auto")
    checklist.append("Check the histogram on the first frame and adjust compensation before the real shots")

    return {
        "scene": {"key": scene_key, "label": scene["label"], "category": scene["category"]},
        "light_condition": {"key": cond_key, "label": cond["label"]},
        "subject": {"key": move_key, "label": movement["label"],
                    "required_shutter": shutter_label(required_shutter)},
        "location": {"lat": lat, "lon": lon, "tz": tz_name, "date": date_str,
                     "city": payload.get("city") or ""},
        "sun": day_info,
        "sun_at_shoot": {
            "time": shoot_time or "sunset - 45m",
            "altitude": round(sun_alt, 2),
            "azimuth": round(sun_az, 1),
            "azimuth_name": _azimuth_name(sun_az),
            "advice": sun_advice,
        },
        "plan": {
            "ev100_target": round(ev_target, 2),
            "ev100_range": scene["ev_range"],
            "ev100_check": round(ev_check, 2) if ev_check else None,
            "aperture": aperture_label(aperture),
            "shutter": shutter_label(snapped_shutter),
            "shutter_seconds": round(snapped_shutter, 4),
            "iso": chosen_iso,
            "iso_max": iso_max,
            "metering": scene["metering"],
            "focus": scene["focus"],
            "shutter_hint": scene["shutter_hint"],
            "handheld_rule": shutter_label(handheld_rule),
            "required_shutter": shutter_label(required_shutter),
            "aperture_ladder": ladder,
            "nd_table": nd_table,
            "recommended_nd": ((recommended_nd["filter"] + " -> " + recommended_nd["shutter"])
                               if recommended_nd else None),
            "solver_note": solved["note"],
            "pitfalls": scene["pitfalls"],
        },
        "axes": axes,
        "weights": weights,
        "score": score,
        "verdict": verdict_key,
        "verdict_label": verdict_label,
        "in_window": in_window,
        "windows": [{"key": k, "start": min_to_hhmm(s), "end": min_to_hhmm(e)}
                     for k, (s, e) in ideal_windows],
        "flags": sorted(flags, key=lambda f: {"high": 0, "medium": 1, "low": 2}[f["severity"]]),
        "checklist": checklist,
        "moon": day_info.get("moon"),
        "notes": payload.get("notes") or "",
    }


def sample_payload():
    """A demo plan used by the 'load sample' button."""
    return {
        "city": "Chicago",
        "lat": 41.8781,
        "lon": -87.6298,
        "tz": "America/Chicago",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "scene": "golden_hour_portrait",
        "light_condition": "golden",
        "subject": "walking",
        "shoot_time": "17:20",
        "focal_length": 85,
        "crop": 1.0,
        "iso_max": 3200,
        "aperture": 2.8,
        "gear": {"tripod": False, "nd": False, "flash": False,
                 "reflector": True, "polarizer": False, "diffuser": False},
        "notes": "Golden-hour portraits at the Botanic Garden, subject arriving at 17:20.",
    }
