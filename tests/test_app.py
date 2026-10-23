"""Smoke tests for golden-hour-forge.

Run with:  python3 tests/test_app.py
(also works under pytest if it is installed)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solar import compute_day, minutes_of_day, moon_phase, solar_position  # noqa: E402
import exposure  # noqa: E402
import app as app_module  # noqa: E402

app_module.db.init_db()
client = app_module.app.test_client()


def test_chicago_solar_day():
    day = compute_day("2026-10-23", 41.8781, -87.6298, "America/Chicago")
    assert day["sunrise"] and day["sunset"], "sunrise and sunset must exist"
    sunrise_min = minutes_of_day(day["sunrise"][11:16])
    sunset_min = minutes_of_day(day["sunset"][11:16])
    assert 5 * 60 <= sunrise_min <= 7 * 60 + 30, "sunrise outside expected window: " + day["sunrise"]
    assert 16 * 60 + 45 <= sunset_min <= 18 * 60 + 45, "sunset outside expected window: " + day["sunset"]
    assert day["day_length_minutes"] > 9 * 60, "October day length should exceed 9 hours"
    assert 25 <= day["solar_noon_altitude"] <= 45, "noon altitude implausible: " + str(day["solar_noon_altitude"])
    assert day["polar"] == "none"


def test_golden_hour_windows_exist():
    day = compute_day("2026-10-23", 41.8781, -87.6298, "America/Chicago")
    golden = day["golden_hour_evening"]
    assert golden["start"] and golden["end"], "evening golden hour must exist in October"
    assert 30 <= golden["minutes"] <= 90, "golden hour length implausible: " + str(golden["minutes"])
    blue = day["blue_hour_evening"]
    assert blue["start"] and blue["end"], "evening blue hour must exist"
    start = minutes_of_day(golden["start"][11:16])
    sunset = minutes_of_day(day["sunset"][11:16])
    assert start < sunset, "golden hour should begin before sunset"


def test_polar_night_and_polar_day():
    winter = compute_day("2026-12-21", 69.6492, 18.9553, "Europe/Oslo")
    assert winter["polar"] == "polar_night", "Tromso should be in polar night on Dec 21"
    summer = compute_day("2026-06-21", 69.6492, 18.9553, "Europe/Oslo")
    assert summer["polar"] == "polar_day", "Tromso should be in polar day on Jun 21"


def test_moon_phase():
    moon = moon_phase(2451550.1)
    assert moon["phase"] == "New Moon"
    assert moon["illumination_pct"] < 2
    full = moon_phase(2451550.1 + 14.765)
    assert full["phase"] == "Full Moon", "half cycle should read as Full Moon"
    assert full["illumination_pct"] > 95


def test_sunny_sixteen():
    ev = exposure.ev100_from(16, 1 / 125, 100)
    assert abs(ev - 14.97) < 0.05, "sunny 16 EV100 wrong: " + str(ev)
    t = exposure.shutter_for(15.0, 16, 100)
    assert abs(t - 1 / 128) < 0.001


def test_iso_tradeoff():
    fast = exposure.shutter_for(11.0, 2.8, 100)
    slow = exposure.shutter_for(11.0, 2.8, 400)
    assert abs(slow * 4 - fast) < 1e-6, "doubling ISO twice should halve the shutter"


def test_shutter_labels():
    assert exposure.shutter_label(1 / 250) == "1/250"
    assert exposure.shutter_label(30) == "30s"
    assert exposure.shutter_label(2) == "2s"


def test_golden_hour_portrait_analysis():
    payload = exposure.sample_payload()
    result = exposure.analyze(payload)
    assert 0 <= result["score"] <= 100
    assert result["verdict"] in [v[1] for v in exposure.VERDICT_BANDS]
    assert len(result["axes"]) == 5
    assert result["plan"]["aperture"].startswith("f/")
    assert result["plan"]["iso"] >= 100
    assert result["plan"]["nd_table"], "ND table must exist"
    assert result["checklist"], "checklist must exist"
    assert result["sun"]["sunset"], "sunset must be present"


def test_flags_fire_for_handheld_risk():
    # A dark scene with a long lens and a low ISO ceiling cannot reach a safe
    # handheld shutter speed, so the risk has to be flagged.
    payload = exposure.sample_payload()
    payload.update({"scene": "night_street", "light_condition": "night",
                    "focal_length": 400, "iso_max": 800,
                    "gear": {"tripod": False, "nd": False, "flash": False,
                             "reflector": False, "polarizer": False,
                             "diffuser": False}})
    result = exposure.analyze(payload)
    codes = [f["code"] for f in result["flags"]]
    assert "handheld_risk" in codes, "expected handheld_risk, got " + str(codes)
    assert "cannot_reach_shutter" in codes, "expected cannot_reach_shutter, got " + str(codes)
    assert result["score"] < 85


def test_solver_meets_the_shutter_requirement():
    # In good light the solver should raise ISO as needed rather than flag risk.
    payload = exposure.sample_payload()
    result = exposure.analyze(payload)
    plan = result["plan"]
    assert plan["iso"] <= payload["iso_max"], "ISO must respect the ceiling"
    assert plan["shutter_seconds"] <= payload_shutter(payload), "shutter too slow for the subject"
    assert plan["shutter_seconds"] <= 1.0 / payload["focal_length"], "handheld rule not met"


def payload_shutter(payload):
    return exposure.MOVEMENTS[payload.get("subject", "walking")]["shutter"]


def test_astro_uses_long_exposure():
    payload = exposure.sample_payload()
    payload.update({"scene": "astro", "light_condition": "night", "focal_length": 20,
                    "iso_max": 6400,
                    "gear": {"tripod": True, "nd": False, "flash": False,
                             "reflector": False, "polarizer": False, "diffuser": False}})
    result = exposure.analyze(payload)
    plan = result["plan"]
    assert plan["shutter_seconds"] >= 4, "astro should land on a long exposure: " + plan["shutter"]
    assert plan["iso"] <= 6400


def test_night_street_iso_is_sane():
    payload = exposure.sample_payload()
    payload.update({"scene": "night_street", "light_condition": "night",
                    "focal_length": 35, "iso_max": 6400,
                    "gear": {"tripod": False, "nd": False, "flash": False,
                             "reflector": False, "polarizer": False, "diffuser": False}})
    result = exposure.analyze(payload)
    plan = result["plan"]
    assert 400 <= plan["iso"] <= 6400, "night ISO implausible: " + str(plan["iso"])
    assert plan["shutter_seconds"] <= 0.02, "night shutter too slow: " + plan["shutter"]


def test_missing_gear_is_flagged():
    payload = exposure.sample_payload()
    payload.update({"scene": "astro", "gear": {"tripod": False, "nd": False, "flash": False,
                                               "reflector": False, "polarizer": False,
                                               "diffuser": False}})
    result = exposure.analyze(payload)
    codes = [f["code"] for f in result["flags"]]
    assert "missing_gear_tripod" in codes, "expected missing_gear_tripod, got " + str(codes)


def test_night_scene_needs_tripod():
    payload = exposure.sample_payload()
    payload.update({"scene": "blue_hour_portrait", "light_condition": "blue_hour",
                    "gear": {"tripod": False, "nd": False, "flash": False,
                             "reflector": False, "polarizer": False, "diffuser": False}})
    result = exposure.analyze(payload)
    codes = [f["code"] for f in result["flags"]]
    assert "missing_gear_tripod" in codes, "expected missing_gear_tripod, got " + str(codes)


def test_health_endpoint():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_index_renders():
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Golden Hour Forge" in body
    assert "Chicago" in body


def test_analyze_endpoint():
    payload = exposure.sample_payload()
    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "score" in data and "axes" in data and "sun" in data


def test_scenes_endpoint():
    resp = client.get("/api/scenes")
    data = resp.get_json()
    assert len(data["scenes"]) >= 12
    assert len(data["cities"]) >= 30
    assert any(s["key"] == "golden_hour_portrait" for s in data["scenes"])


def test_solar_endpoint():
    resp = client.get("/api/solar?lat=41.8781&lon=-87.6298&date=2026-10-23&tz=America/Chicago")
    assert resp.status_code == 200
    assert resp.get_json()["sunset"]


def test_sample_endpoint():
    resp = client.get("/api/sample")
    assert resp.status_code == 200
    assert resp.get_json()["scene"] == "golden_hour_portrait"


def test_session_lifecycle():
    payload = exposure.sample_payload()
    resp = client.post("/api/sessions", json={"payload": payload})
    assert resp.status_code == 201
    session_id = resp.get_json()["id"]

    resp = client.get("/api/sessions")
    assert any(s["id"] == session_id for s in resp.get_json()["sessions"])

    resp = client.get("/api/sessions/" + str(session_id))
    assert resp.status_code == 200
    assert resp.get_json()["result"]["score"] >= 0

    resp = client.patch("/api/sessions/" + str(session_id), json={"self_rating": 4, "notes": "shot it"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["self_rating"] == 4
    assert body["notes"] == "shot it"

    resp = client.get("/api/export/" + str(session_id) + "?fmt=md")
    assert resp.status_code == 200
    md = resp.get_data(as_text=True)
    assert "Golden Hour Forge" in md
    assert "Findings" in md

    resp = client.get("/api/export/" + str(session_id) + "?fmt=json")
    assert resp.status_code == 200
    assert resp.get_json()["scene"]["key"] == "golden_hour_portrait"

    client.delete("/api/sessions/" + str(session_id))
    resp = client.get("/api/sessions/" + str(session_id))
    assert resp.status_code == 404


def test_export_missing_session():
    resp = client.get("/api/export/999999")
    assert resp.status_code == 404


def test_all_scenes_analyze_without_error():
    for key in exposure.SCENES:
        payload = exposure.sample_payload()
        payload["scene"] = key
        result = exposure.analyze(payload)
        assert result["score"] >= 0
        assert result["plan"]["shutter"]


def test_all_cities_analyze_without_error():
    for city in exposure.CITIES[:8]:
        payload = exposure.sample_payload()
        payload.update({"city": city["name"], "lat": city["lat"], "lon": city["lon"],
                        "tz": city["tz"]})
        result = exposure.analyze(payload)
        assert result["sun"]["sunrise"] or result["sun"]["polar"] != "none"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS  " + name)
            except AssertionError as exc:
                failures += 1
                print("FAIL  " + name + " -> " + str(exc))
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print("ERROR " + name + " -> " + repr(exc))
    print("")
    print("failures: " + str(failures))
    sys.exit(1 if failures else 0)
