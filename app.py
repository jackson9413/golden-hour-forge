"""Flask API for golden-hour-forge.

Local-first: no API keys, no outbound network calls, no telemetry.
Run with:  python3 app.py   then open http://127.0.0.1:5057
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

from flask import Flask, jsonify, request, render_template, Response

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db  # noqa: E402
import exposure  # noqa: E402
import exports  # noqa: E402
from solar import compute_day  # noqa: E402

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

CITY_BY_NAME = {c["name"].lower(): c for c in exposure.CITIES}


def _render():
    boot = {
        "today": datetime.now().strftime("%Y-%m-%d"),
        "scene_count": len(exposure.SCENES),
        "city_count": len(exposure.CITIES),
    }
    return render_template("index.html", scenes=exposure.SCENES,
                           conditions=exposure.LIGHT_CONDITIONS,
                           movements=exposure.MOVEMENTS,
                           cities=exposure.CITIES, boot=boot)


@app.route("/")
def index():
    return _render()


def _payload_from_request(raw):
    """Normalise a client payload: resolve city names, clamp numbers."""
    data = dict(raw or {})
    city = str(data.get("city") or "").strip()
    if city and city.lower() in CITY_BY_NAME:
        entry = CITY_BY_NAME[city.lower()]
        data.setdefault("lat", entry["lat"])
        data.setdefault("lon", entry["lon"])
        data.setdefault("tz", entry["tz"])
        if not data.get("lat"):
            data["lat"] = entry["lat"]
        if not data.get("lon"):
            data["lon"] = entry["lon"]
        if not data.get("tz"):
            data["tz"] = entry["tz"]
    try:
        data["lat"] = float(data.get("lat", 41.8781))
        data["lon"] = float(data.get("lon", -87.6298))
    except Exception:
        data["lat"] = 41.8781
        data["lon"] = -87.6298
    data["lat"] = max(-89.0, min(89.0, data["lat"]))
    data["lon"] = max(-180.0, min(180.0, data["lon"]))
    try:
        data["focal_length"] = float(data.get("focal_length") or 50)
    except Exception:
        data["focal_length"] = 50
    try:
        data["crop"] = float(data.get("crop") or 1.0)
    except Exception:
        data["crop"] = 1.0
    try:
        data["iso_max"] = int(data.get("iso_max") or 3200)
    except Exception:
        data["iso_max"] = 3200
    data["iso_max"] = max(50, min(102400, data["iso_max"]))
    if not data.get("date"):
        data["date"] = datetime.now().strftime("%Y-%m-%d")
    return data


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    raw = request.get_json(silent=True) or {}
    payload = _payload_from_request(raw)
    try:
        result = exposure.analyze(payload)
    except Exception as exc:  # pragma: no cover - defensive
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.route("/api/scenes")
def api_scenes():
    out = []
    for key, scene in exposure.SCENES.items():
        out.append({
            "key": key,
            "label": scene["label"],
            "category": scene["category"],
            "ev_range": scene["ev_range"],
            "windows": scene["windows"],
            "gear_required": scene["gear_required"],
            "gear_optional": scene["gear_optional"],
        })
    return jsonify({"scenes": out,
                    "conditions": [{"key": k, "label": v["label"]}
                                   for k, v in exposure.LIGHT_CONDITIONS.items()],
                    "movements": [{"key": k, "label": v["label"],
                                   "shutter": exposure.shutter_label(v["shutter"])}
                                  for k, v in exposure.MOVEMENTS.items()],
                    "cities": exposure.CITIES})


@app.route("/api/cities")
def api_cities():
    return jsonify({"cities": exposure.CITIES})


@app.route("/api/solar")
def api_solar():
    lat = request.args.get("lat", type=float, default=41.8781)
    lon = request.args.get("lon", type=float, default=-87.6298)
    date = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    tz = request.args.get("tz") or "America/Chicago"
    try:
        return jsonify(compute_day(date, lat, lon, tz))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/sample")
def api_sample():
    return jsonify(exposure.sample_payload())


@app.route("/api/sessions", methods=["GET"])
def api_sessions_list():
    return jsonify({"sessions": db.list_sessions(
        request.args.get("limit", default=50, type=int))})


@app.route("/api/sessions", methods=["POST"])
def api_sessions_create():
    raw = request.get_json(silent=True) or {}
    payload = _payload_from_request(raw.get("payload") or raw)
    result = exposure.analyze(payload)
    session_id = db.create_session(result, payload)
    return jsonify({"id": session_id, "session": db.get_session(session_id)}), 201


@app.route("/api/sessions/<int:session_id>", methods=["GET"])
def api_session_get(session_id):
    row = db.get_session(session_id)
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)


@app.route("/api/sessions/<int:session_id>", methods=["PATCH"])
def api_session_patch(session_id):
    raw = request.get_json(silent=True) or {}
    row = db.update_session(session_id, raw.get("self_rating"), raw.get("notes"))
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)


@app.route("/api/sessions/<int:session_id>", methods=["DELETE"])
def api_session_delete(session_id):
    db.delete_session(session_id)
    return jsonify({"deleted": True, "id": session_id})


@app.route("/api/export/<int:session_id>")
def api_export(session_id):
    row = db.get_session(session_id)
    if not row:
        return jsonify({"error": "not found"}), 404
    result = row.get("result") or {}
    fmt = (request.args.get("fmt") or "md").lower()
    if fmt == "json":
        body = exports.to_json(result)
        mimetype = "application/json"
        filename = "golden-hour-%d.json" % session_id
    else:
        body = exports.to_markdown(result)
        mimetype = "text/markdown"
        filename = "golden-hour-%d.md" % session_id
    return Response(body, mimetype=mimetype, headers={
        "Content-Disposition": 'attachment; filename="%s"' % filename})


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok", "service": "golden-hour-forge",
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "not found"}), 404
    return _render(), 404


db.init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5057"))
    print("golden-hour-forge running on http://127.0.0.1:%d" % port)
    app.run(host="127.0.0.1", port=port, debug=False)
