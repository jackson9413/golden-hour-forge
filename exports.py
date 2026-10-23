"""Export helpers for golden-hour-forge (Markdown + JSON)."""

from __future__ import annotations

import json


def _band(score):
    if score >= 85:
        return "SHOOT READY"
    if score >= 70:
        return "MOSTLY READY"
    if score >= 55:
        return "NEEDS SETUP"
    if score >= 40:
        return "TIGHT BUT USABLE"
    return "NEEDS REWORK"


def to_json(result):
    return json.dumps(result, indent=2, ensure_ascii=False)


def to_markdown(result):
    lines = []
    add = lines.append

    sun = result.get("sun") or {}
    plan = result.get("plan") or {}
    loc = result.get("location") or {}
    scene = result.get("scene") or {}
    cond = result.get("light_condition") or {}
    subject = result.get("subject") or {}

    add("# Golden Hour Forge - shoot plan")
    add("")
    add("**Scene:** " + scene.get("label", "") + "  ")
    add("**Light:** " + cond.get("label", "") + "  ")
    add("**Subject:** " + subject.get("label", "") + "  ")
    add("**Location:** " + (loc.get("city") or "custom")
        + " (" + str(loc.get("lat")) + ", " + str(loc.get("lon")) + ")  ")
    add("**Date:** " + str(loc.get("date")) + " " + str(loc.get("tz")) + "  ")
    add("")
    add("## Score: " + str(result.get("score")) + "/100 - " + _band(result.get("score") or 0))
    add("")
    axes = result.get("axes") or {}
    for key, value in axes.items():
        add("- " + key.capitalize() + ": " + str(value) + "/100")
    add("")

    add("## Recommended settings")
    add("")
    add("| Setting | Value |")
    add("| --- | --- |")
    add("| Aperture | " + str(plan.get("aperture")) + " |")
    add("| Shutter | " + str(plan.get("shutter")) + " |")
    add("| ISO | " + str(plan.get("iso")) + " |")
    add("| EV100 target | " + str(plan.get("ev100_target")) + " |")
    add("| Metering | " + str(plan.get("metering")) + " |")
    add("| Focus | " + str(plan.get("focus")) + " |")
    add("| Handheld rule | " + str(plan.get("handheld_rule")) + " |")
    add("| Subject needs | " + str(plan.get("required_shutter")) + " |")
    add("")

    sun_at = result.get("sun_at_shoot") or {}
    add("## Sun at shoot time (" + str(sun_at.get("time")) + ")")
    add("")
    add("- Altitude: " + str(sun_at.get("altitude")) + " deg")
    add("- Azimuth: " + str(sun_at.get("azimuth")) + " deg (" + str(sun_at.get("azimuth_name")) + ")")
    add("- " + str(sun_at.get("advice")))
    add("")

    add("## Light windows")
    add("")
    add("| Event | Time |")
    add("| --- | --- |")
    for label, key in (("Sunrise", "sunrise"), ("Solar noon", "solar_noon"),
                       ("Sunset", "sunset"), ("Civil dawn", "civil_dawn"),
                       ("Civil dusk", "civil_dusk")):
        if sun.get(key):
            add("| " + label + " | " + str(sun.get(key)) + " |")
    for label, key in (("Golden hour (morning)", "golden_hour_morning"),
                       ("Golden hour (evening)", "golden_hour_evening"),
                       ("Blue hour (morning)", "blue_hour_morning"),
                       ("Blue hour (evening)", "blue_hour_evening")):
        block = sun.get(key) or {}
        if block.get("start"):
            add("| " + label + " | " + block["start"] + " to " + block["end"] + " |")
    moon = sun.get("moon") or {}
    if moon:
        add("| Moon | " + str(moon.get("phase")) + " " + str(moon.get("illumination_pct")) + "% lit |")
    add("")

    ladder = plan.get("aperture_ladder") or []
    if ladder:
        add("## Aperture ladder")
        add("")
        add("| Aperture | Shutter at ISO " + str(ladder[0].get("iso_used"))
            + " | Shutter at ISO 1600 | Shutter at ISO " + str(ladder[0].get("iso_chosen")) + " |")
        add("| --- | --- | --- | --- |")
        for row in ladder:
            add("| " + str(row.get("aperture")) + " | " + str(row.get("shutter_at_base_iso"))
                + " | " + str(row.get("shutter_at_iso1600")) + " | "
                + str(row.get("shutter_at_chosen_iso")) + " |")
        add("")
    if plan.get("recommended_nd"):
        add("Recommended ND: " + str(plan.get("recommended_nd")))
        add("")

    nd_table = plan.get("nd_table") or []
    if nd_table:
        add("## ND filter table")
        add("")
        add("| Filter | Shutter | Tripod |")
        add("| --- | --- | --- |")
        for row in nd_table:
            add("| " + str(row.get("filter")) + " | " + str(row.get("shutter"))
                + " | " + ("yes" if row.get("needs_tripod") else "no") + " |")
        add("")

    flags = result.get("flags") or []
    if flags:
        add("## Findings")
        add("")
        for item in flags:
            add("### [" + str(item.get("severity")).upper() + "] " + str(item.get("title")))
            add("")
            add("- Why: " + str(item.get("evidence")))
            add("- Fix: " + str(item.get("fix")))
            add("")

    checklist = result.get("checklist") or []
    if checklist:
        add("## Shot checklist")
        add("")
        for item in checklist:
            add("- [ ] " + str(item))
        add("")

    pitfalls = plan.get("pitfalls") or []
    if pitfalls:
        add("## Watch out for")
        add("")
        for item in pitfalls:
            add("- " + str(item))
        add("")

    if result.get("notes"):
        add("## Notes")
        add("")
        add(str(result.get("notes")))
        add("")

    return chr(10).join(lines)
