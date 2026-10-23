# Golden Hour Forge

**A local-first photography light and exposure planner.** Pick a scene, a date and a place;
get back the exact golden hour and blue hour windows for that day, a ready-to-dial camera
setting, an aperture ladder, an ND filter table, and a list of the things that are about to
go wrong.

No API keys. No accounts. No network calls. Runs entirely on your machine.

---

## What it does

**1. Real sun times for any date and place.**
Full sunrise, sunset, solar noon, civil/nautical/astronomical twilight, golden hour and blue
hour windows, computed with Meeus low-precision solar position (about 0.01 degree accurate).
Polar day and polar night are detected and reported instead of silently returning nonsense.
44 built-in cities plus any custom latitude, longitude and timezone.

**2. A solved exposure, not a guess.**
Give it a scene (16 presets), a light condition, how fast the subject moves, your focal length
and your ISO ceiling. It solves for aperture, shutter and ISO that actually satisfy the
constraint: fast enough to freeze the subject, slow enough to avoid noise, and inside the
gear you own. Astro flips the rule and targets the 300 rule instead.

**3. Aperture ladder and ND filter table.**
See the shutter speed at every neighbouring f-stop at three ISO values, and see what each ND
filter does to your shutter time, including whether you now need a tripod.

**4. A five-axis shoot-readiness score.**
Light quality / timing / stability / gear ready / dynamic range, weighted per scene category,
with five verdict bands from SHOOT READY down to NEEDS REWORK.

**5. Findings with fixes, not just scores.**
Shoot outside the good window. Handheld shake at 400mm. Backlight with no fill. Missing an ND
filter. A bright moon washing out an astro shot. Each finding carries the evidence and the
concrete thing to do about it.

**6. Sun-through-the-day chart.**
An SVG curve of solar altitude across the local day with the golden hour, blue hour and your
arrival time drawn on it, plus the sun's altitude and compass bearing at your shoot time.

**7. Session log and exports.**
Save plans to SQLite, rate them 1 to 5 stars, add notes, and export any session as Markdown
or JSON.

---

## Why it matters

Photographers plan around the light and then get the exposure wrong, or they pick the exposure
first and show up when the light is gone. Golden Hour Forge answers the real question:

**When is the good light, where is the sun, and what do I dial in when I get there?**

in one pass, with the physics checked rather than approximated.

It is the tool you want at 6pm the night before a shoot, when you want to know whether to set
your alarm for 6:40am, whether to bring the reflector, and whether 1/60 at f/1.8 is going to
give you a blurry mess at 85mm.

---

## Tech stack

- **Backend:** Python 3.9+, Flask 3, SQLite via the standard library
- **Frontend:** vanilla HTML, CSS and JS. No build step, no framework, no CDN
- **Solar math:** custom Meeus low-precision implementation, pure Python
- **Exposure math:** EV100-based solver with a real ISO / aperture / shutter trade-off
- **Dependencies:** Flask only
- **Network:** zero outbound requests at runtime

---

## How to run

    cd golden-hour-forge
    python3 -m venv .venv && source .venv/bin/activate    # optional
    pip install -r requirements.txt
    python3 app.py

Then open **http://127.0.0.1:5057**

Change the port with the PORT environment variable (for example PORT=8080 python3 app.py).

### Run the tests

    python3 tests/test_app.py        # 24 smoke tests, pytest not required

### Try it from the API

    curl -s -X POST http://127.0.0.1:5057/api/analyze -H 'Content-Type: application/json' -d '{"city": "Chicago", "date": "2026-10-23", "scene": "golden_hour_portrait", "light_condition": "golden", "subject": "walking", "shoot_time": "17:20", "focal_length": 85, "iso_max": 3200, "gear": {"reflector": true}}'

---

## REST API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | /api/analyze | Full plan from a shoot brief |
| GET | /api/solar?lat=&lon=&date=&tz= | Sun and moon events for a day |
| GET | /api/scenes | Scene, condition, movement and city catalogues |
| GET | /api/cities | City coordinates and timezones |
| GET | /api/sample | Demo payload for the sample button |
| GET | /api/sessions | Saved plans |
| POST | /api/sessions | Analyse and save a plan |
| GET | /api/sessions/<id> | One saved plan |
| PATCH | /api/sessions/<id> | Set self_rating (1-5) and notes |
| DELETE | /api/sessions/<id> | Delete a saved plan |
| GET | /api/export/<id>?fmt=md | Download Markdown |
| GET | /api/export/<id>?fmt=json | Download JSON |
| GET | /api/health | Liveness check |

---

## The 16 scenes

Golden-hour portrait, backlit portrait, blue-hour portrait, harsh midday portrait, overcast
street, indoor event, night street, sports action, wildlife, landscape wide, long exposure
(silky water), macro, food, concert stage, and astro.

Each one carries its own EV100 range, aperture, metering mode, focus strategy, gear
requirements, pitfalls and shot checklist.

---

## How the math works

- **Solar position:** Meeus low-precision. The sun's altitude is sampled every minute across
  the local day and threshold crossings are interpolated, which is why polar day and polar
  night are handled without special cases.
- **Golden hour:** sun between -4 and +6 degrees. **Blue hour:** sun between -4 and -6 degrees.
- **EV100:** EV100 = log2(N squared / t) minus log2(ISO / 100). A target light level plus your
  chosen aperture fixes the shutter: t = (N squared / 2 to the EV100) times (100 / ISO).
- **Solver:** given the subject's minimum shutter speed, the handheld floor of
  1 / (focal length x crop factor) and your ISO ceiling, it picks the lowest ISO that hits
  the requirement, opens the aperture only if ISO alone cannot get there, and tells you when
  the scene is physically impossible.
- **Astro:** the constraint inverts, because a long exposure is the goal, so the solver targets
  the 300 rule (300 divided by focal length) and widens the aperture when the ISO ceiling
  cannot reach it.
- **ND filters:** an ND filter darkens the scene, so the exposure time goes UP by a factor of
  2 per stop. The table shows the real shutter at each filter strength and flags when you
  cross into tripod territory.

Accuracy was cross-checked against an independent NOAA-style sunrise equation and against
the equation of time: solar noon lands within a minute of the reference value and day length
within three minutes.

---

## Project layout

    golden-hour-forge/
      app.py            Flask routes and API
      solar.py          Sun position, twilight windows, moon phase
      exposure.py       Scenes, EV100 solver, scoring, findings
      db.py             SQLite session log
      exports.py        Markdown and JSON export
      templates/
        index.html      Single page UI
      static/
        app.js          Front-end logic and the sun chart
        style.css       Dark theme
      tests/
        test_app.py     24 smoke tests
      requirements.txt

---

## Privacy

Everything is stored in data/golden_hour.db on your machine. There is no telemetry, no
account, no outbound request and no API key anywhere in this project. Delete the data folder
to erase your saved plans.

---

## License

MIT. Use it, fork it, shoot better.
