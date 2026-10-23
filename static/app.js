/* Golden Hour Forge - front end. Vanilla JS, no build step, no dependencies. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  var state = { result: null, payload: null, sessionId: null };

  var VERDICT_COLOR = {
    shoot_ready: "#3ecf8e",
    mostly_ready: "#7c9cff",
    needs_setup: "#e3c34a",
    tight_but_usable: "#e88a3b",
    needs_rework: "#ef5f5f"
  };

  function axisColor(v) {
    if (v >= 80) return "#3ecf8e";
    if (v >= 65) return "#7c9cff";
    if (v >= 50) return "#e3c34a";
    if (v >= 35) return "#e88a3b";
    return "#ef5f5f";
  }

  function esc(s) {
    return String(s === undefined || s === null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function collectPayload() {
    var gear = {};
    ["tripod", "nd", "flash", "reflector", "polarizer", "diffuser"].forEach(function (k) {
      gear[k] = $("gear_" + k).checked;
    });
    return {
      city: $("city").value,
      lat: parseFloat($("lat").value),
      lon: parseFloat($("lon").value),
      tz: $("tz").value,
      date: $("date").value,
      shoot_time: $("shootTime").value,
      scene: $("scene").value,
      light_condition: $("lightCondition").value,
      subject: $("subject").value,
      focal_length: parseFloat($("focal").value) || 50,
      crop: parseFloat($("crop").value) || 1,
      iso_max: parseInt($("isoMax").value, 10) || 3200,
      aperture: $("aperture").value ? parseFloat($("aperture").value) : null,
      gear: gear,
      notes: $("notes").value
    };
  }

  function showError(msg) {
    var results = $("results");
    var old = results.querySelector(".err");
    if (old) old.remove();
    var div = document.createElement("div");
    div.className = "err";
    div.textContent = msg;
    results.insertBefore(div, results.firstChild);
  }

  function clearError() {
    var old = document.querySelector(".err");
    if (old) old.remove();
  }

  /* ------------------------------------------------------------------ */
  /* sun chart                                                          */
  /* ------------------------------------------------------------------ */
  function buildSunChart(sun, shootMin) {
    var W = 1000, H = 175, padL = 36, padR = 10, padT = 12, padB = 24;
    var tl = sun.timeline || [];
    if (!tl.length) return "";
    var maxAlt = 25;
    tl.forEach(function (p) { if (p.altitude > maxAlt) maxAlt = p.altitude; });
    maxAlt = Math.min(90, Math.ceil((maxAlt + 8) / 10) * 10);
    var minAlt = -22;

    function x(m) { return padL + (m / 1440) * (W - padL - padR); }
    function y(a) { return padT + (1 - (a - minAlt) / (maxAlt - minAlt)) * (H - padT - padB); }

    var svg = '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none">';

    // night band below the horizon
    svg += '<rect x="' + padL + '" y="' + y(0) + '" width="' + (W - padL - padR) +
      '" height="' + (H - padB - y(0)) + '" fill="#141a24"/>';

    // golden and blue windows
    var bands = [
      ["golden_hour_morning", "#f0a93b", 0.16],
      ["golden_hour_evening", "#f0a93b", 0.16],
      ["blue_hour_morning", "#5aa9e6", 0.13],
      ["blue_hour_evening", "#5aa9e6", 0.13]
    ];
    bands.forEach(function (b) {
      var blk = sun[b[0]];
      if (!blk || !blk.start) return;
      var m1 = hhmmToMin(blk.start);
      var m2 = hhmmToMin(blk.end);
      if (m1 === null || m2 === null) return;
      svg += '<rect x="' + x(m1) + '" y="' + padT + '" width="' + Math.max(1, x(m2) - x(m1)) +
        '" height="' + (H - padT - padB) + '" fill="' + b[1] + '" opacity="' + b[2] + '"/>';
    });

    // horizon + golden thresholds
    [[0, "#4a5costs"], [0, "#465064"], [6, "#7a5c1e"], [-4, "#26405c"], [-6, "#1f3a52"]].forEach(function (t) {
      if (t[1] === "#4a5costs") return;
      svg += '<line x1="' + padL + '" x2="' + (W - padR) + '" y1="' + y(t[0]) + '" y2="' + y(t[0]) +
        '" stroke="' + t[1] + '" stroke-width="1" stroke-dasharray="3 4"/>';
    });

    // altitude curve
    var pts = tl.map(function (p) { return x(p.minutes).toFixed(1) + "," + y(p.altitude).toFixed(1); });
    svg += '<polyline points="' + pts.join(" ") + '" fill="none" stroke="#f0a93b" stroke-width="2"/>';

    // area under curve above the horizon
    var area = tl.filter(function (p) { return p.altitude > 0; }).map(function (p) {
      return x(p.minutes).toFixed(1) + "," + y(p.altitude).toFixed(1);
    });
    if (area.length > 1) {
      var first = tl.filter(function (p) { return p.altitude > 0; })[0];
      var last = tl.filter(function (p) { return p.altitude > 0; }).pop();
      svg += '<polygon points="' + x(first.minutes).toFixed(1) + "," + y(0).toFixed(1) + " " +
        area.join(" ") + " " + x(last.minutes).toFixed(1) + "," + y(0).toFixed(1) +
        '" fill="#f0a93b" opacity="0.07"/>';
    }

    // hour ticks
    for (var h = 0; h <= 24; h += 3) {
      svg += '<text x="' + x(h * 60).toFixed(1) + '" y="' + (H - 6) +
        '" fill="#66748a" font-size="10" text-anchor="middle">' + h + ":00</text>";
    }
    svg += '<text x="' + (padL - 6) + '" y="' + (y(0) + 3).toFixed(1) +
      '" fill="#66748a" font-size="10" text-anchor="end">0</text>';
    svg += '<text x="' + (padL - 6) + '" y="' + (y(maxAlt) + 8).toFixed(1) +
      '" fill="#66748a" font-size="10" text-anchor="end">' + maxAlt + "</text>";

    // shoot-time marker
    if (shootMin !== null && shootMin !== undefined) {
      var alt = altitudeAt(tl, shootMin);
      svg += '<line x1="' + x(shootMin).toFixed(1) + '" x2="' + x(shootMin).toFixed(1) +
        '" y1="' + padT + '" y2="' + (H - padB) + '" stroke="#ef5f5f" stroke-width="1.5"/>';
      svg += '<circle cx="' + x(shootMin).toFixed(1) + '" cy="' + y(alt).toFixed(1) +
        '" r="5" fill="#ef5f5f" stroke="#0b0e13" stroke-width="2"/>';
    }
    svg += "</svg>";
    return svg;
  }

  function altitudeAt(tl, minutes) {
    if (!tl.length) return 0;
    for (var i = 0; i < tl.length - 1; i++) {
      if (minutes >= tl[i].minutes && minutes <= tl[i + 1].minutes) {
        var span = tl[i + 1].minutes - tl[i].minutes || 1;
        var f = (minutes - tl[i].minutes) / span;
        return tl[i].altitude + (tl[i + 1].altitude - tl[i].altitude) * f;
      }
    }
    return 0;
  }

  function hhmmToMin(s) {
    if (!s) return null;
    var parts = String(s).split(":");
    if (parts.length < 2) return null;
    var h = parseInt(parts[0], 10);
    var m = parseInt(parts[1], 10);
    if (isNaN(h) || isNaN(m)) return null;
    return h * 60 + m;
  }

  /* ------------------------------------------------------------------ */
  /* rendering                                                          */
  /* ------------------------------------------------------------------ */
  function render(result) {
    state.result = result;
    $("emptyState").classList.add("hidden");
    $("plan").classList.remove("hidden");
    $("saveBtn").disabled = false;

    var v = VERDICT_COLOR[result.verdict] || "#7c9cff";
    $("scoreValue").textContent = result.score;
    var pill = $("verdictPill");
    pill.textContent = result.verdict_label;
    pill.style.background = v + "22";
    pill.style.color = v;
    pill.style.border = "1px solid " + v + "66";

    var axes = result.axes || {};
    var axisNames = {
      light: "Light quality", timing: "Timing", stability: "Stability",
      gear: "Gear ready", headroom: "Dynamic range"
    };
    $("axisPills").innerHTML = Object.keys(axes).map(function (k) {
      var c = axisColor(axes[k]);
      return '<div class="axis-pill"><span class="dot" style="background:' + c + '"></span>' +
        esc(axisNames[k] || k) + " <b>" + axes[k] + "</b></div>";
    }).join("");

    var sun = result.sun || {};
    var shootMin = hhmmToMin((result.sun_at_shoot || {}).time);
    $("sunChart").innerHTML = buildSunChart(sun, shootMin);
    $("sunAdvice").textContent = (result.sun_at_shoot || {}).advice || "";

    var rows = [
      ["Sunrise", sun.sunrise], ["Solar noon", sun.solar_noon], ["Sunset", sun.sunset],
      ["Civil dawn", sun.civil_dawn], ["Civil dusk", sun.civil_dusk],
      ["Nautical dawn", sun.nautical_dawn], ["Astronomical dusk", sun.astronomical_dusk]
    ];
    var gRows = [];
    [["Golden hour (morning)", sun.golden_hour_morning],
     ["Golden hour (evening)", sun.golden_hour_evening],
     ["Blue hour (morning)", sun.blue_hour_morning],
     ["Blue hour (evening)", sun.blue_hour_evening]].forEach(function (pair) {
      var b = pair[1];
      if (b && b.start) {
        gRows.push('<tr><td>' + esc(pair[0]) + "</td><td>" + esc(b.start) + " to " +
          esc(b.end) + "</td><td>" + (b.minutes || "?") + " min</td></tr>");
      }
    });
    var moon = sun.moon || {};
    if (moon.phase) {
      gRows.push('<tr><td>Moon</td><td>' + esc(moon.phase) + "</td><td>" +
        moon.illumination_pct + "% lit</td></tr>");
    }
    if (sun.day_length_minutes) {
      gRows.push('<tr><td>Day length</td><td>-</td><td>' +
        Math.floor(sun.day_length_minutes / 60) + "h " +
        Math.round(sun.day_length_minutes % 60) + "m</td></tr>");
    }
    $("windowTable").innerHTML =
      "<tr><th>Event</th><th>Time</th><th>Length</th></tr>" +
      rows.filter(function (r) { return r[1]; })
        .map(function (r) { return "<tr><td>" + esc(r[0]) + "</td><td>" + esc(r[1]) + "</td><td>-</td></tr>"; })
        .join("") + gRows.join("");

    var plan = result.plan || {};
    var settings = [
      ["Aperture", plan.aperture, "chosen for the scene"],
      ["Shutter", plan.shutter, "subject needs " + (plan.required_shutter || "")],
      ["ISO", plan.iso, "ceiling " + plan.iso_max],
      ["EV100", plan.ev100_target, "range " + (plan.ev_range || []).join(" to ")],
      ["Metering", plan.metering, ""],
      ["Focus", plan.focus, ""]
    ];
    $("settingsGrid").innerHTML = settings.map(function (s) {
      return '<div class="setting"><div class="k">' + esc(s[0]) + '</div><div class="v">' +
        esc(s[1]) + '</div><div class="n">' + esc(s[2] || "") + "</div></div>";
    }).join("");
    $("pitfallList").innerHTML = (plan.pitfalls || []).map(function (p) {
      return "<li>" + esc(p) + "</li>";
    }).join("");

    var lad = plan.aperture_ladder || [];
    $("ladderTable").innerHTML =
      "<tr><th>Aperture</th><th>ISO " + (lad[0] ? lad[0].iso_used : "") +
      "</th><th>ISO 1600</th><th>ISO " + (lad[0] ? lad[0].iso_chosen : "") + "</th></tr>" +
      lad.map(function (r) {
        return "<tr><td>" + esc(r.aperture) + "</td><td>" + esc(r.shutter_at_base_iso) +
          "</td><td>" + esc(r.shutter_at_iso1600) + "</td><td>" +
          esc(r.shutter_at_chosen_iso) + "</td></tr>";
      }).join("");

    $("ndTable").innerHTML =
      "<tr><th>Filter</th><th>Shutter</th><th>Tripod</th></tr>" +
      (plan.nd_table || []).map(function (r) {
        return "<tr><td>" + esc(r.filter) + "</td><td>" + esc(r.shutter) + "</td><td>" +
          (r.needs_tripod ? "yes" : "no") + "</td></tr>";
      }).join("");

    var flags = result.flags || [];
    $("flagsList").innerHTML = flags.length
      ? flags.map(function (f) {
        return '<div class="flag ' + esc(f.severity) + '"><div class="ft"><span class="sev ' +
          esc(f.severity) + '">' + esc(f.severity) + "</span>" + esc(f.title) + "</div>" +
          '<div class="fe">' + esc(f.evidence) + "</div>" +
          '<div class="ff">' + esc(f.fix) + "</div></div>";
      }).join("")
      : '<p class="muted">Nothing flagged. The light, the timing and the gear all line up.</p>';

    $("checklist").innerHTML = (result.checklist || []).map(function (c, i) {
      return '<li data-i="' + i + '">' + esc(c) + "</li>";
    }).join("");
    Array.prototype.forEach.call($("checklist").children, function (li) {
      li.addEventListener("click", function () { li.classList.toggle("done"); });
    });

    $("scoreSummary").textContent = result.scene.label + " at " +
      (result.location.city || "custom location") + " on " + result.location.date +
      ". " + (result.in_window ? "You are inside the good window." :
        "You are outside the ideal light window for this scene.");
  }

  /* ------------------------------------------------------------------ */
  /* history                                                            */
  /* ------------------------------------------------------------------ */
  function loadHistory() {
    fetch("/api/sessions")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var list = data.sessions || [];
        if (!list.length) {
          $("historyList").innerHTML = '<p class="muted">No saved plans yet.</p>';
          return;
        }
        $("historyList").innerHTML = list.map(function (s) {
          var c = VERDICT_COLOR[s.verdict] || "#7c9cff";
          return '<div class="hrow" data-id="' + s.id + '">' +
            '<div class="hs" style="color:' + c + '">' + s.score + "</div>" +
            '<div><div>' + esc(s.title) + '</div><div class="hm">' + esc(s.city || "custom") +
            " - " + esc(s.shoot_date) + " - " + esc(s.created_at) + "</div></div>" +
            '<div><input class="hn" placeholder="notes" value="' + esc(s.notes || "") + '"></div>' +
            '<div><input class="hr" type="number" min="1" max="5" placeholder="1-5" value="' +
            (s.self_rating || "") + '"></div>' +
            '<div><a class="dl" href="/api/export/' + s.id + '?fmt=md">MD</a>' +
            '<a class="dl" href="/api/export/' + s.id + '?fmt=json">JSON</a></div>' +
            "</div>";
        }).join("");

        Array.prototype.forEach.call(document.querySelectorAll(".hrow"), function (row) {
          var id = row.getAttribute("data-id");
          row.querySelector(".hn").addEventListener("change", function () {
            patchSession(id, { notes: this.value });
          });
          row.querySelector(".hr").addEventListener("change", function () {
            patchSession(id, { self_rating: this.value });
          });
        });
      })
      .catch(function () { /* history is best effort */ });
  }

  function patchSession(id, data) {
    fetch("/api/sessions/" + id, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    }).then(loadHistory);
  }

  /* ------------------------------------------------------------------ */
  /* actions                                                            */
  /* ------------------------------------------------------------------ */
  function runAnalyze() {
    clearError();
    var payload = collectPayload();
    state.payload = payload;
    $("analyzeBtn").disabled = true;
    fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.j.error || "analysis failed");
        render(res.j);
      })
      .catch(function (e) { showError("Could not build the plan: " + e.message); })
      .finally(function () { $("analyzeBtn").disabled = false; });
  }

  function saveSession() {
    if (!state.payload) return;
    fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ payload: state.payload })
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        state.sessionId = j.id;
        loadHistory();
      })
      .catch(function (e) { showError("Could not save the session: " + e.message); });
  }

  function loadSample() {
    fetch("/api/sample")
      .then(function (r) { return r.json(); })
      .then(function (p) {
        $("city").value = p.city || "";
        $("lat").value = p.lat; $("lon").value = p.lon; $("tz").value = p.tz;
        $("date").value = p.date; $("shootTime").value = p.shoot_time;
        $("scene").value = p.scene; $("lightCondition").value = p.light_condition;
        $("subject").value = p.subject; $("focal").value = p.focal_length;
        $("crop").value = p.crop; $("isoMax").value = p.iso_max;
        $("aperture").value = p.aperture ? String(p.aperture) : "";
        $("notes").value = p.notes || "";
        Object.keys(p.gear || {}).forEach(function (k) {
          var box = $("gear_" + k);
          if (box) box.checked = !!p.gear[k];
        });
        runAnalyze();
      });
  }

  function initCityWatcher() {
    $("city").addEventListener("change", function () {
      var opt = this.options[this.selectedIndex];
      if (!opt || !opt.dataset.lat) return;
      $("lat").value = opt.dataset.lat;
      $("lon").value = opt.dataset.lon;
      $("tz").value = opt.dataset.tz;
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var today = new Date();
    $("date").value = today.getFullYear() + "-" +
      String(today.getMonth() + 1).padStart(2, "0") + "-" +
      String(today.getDate()).padStart(2, "0");
    $("analyzeBtn").addEventListener("click", runAnalyze);
    $("analyzeBtn2").addEventListener("click", runAnalyze);
    $("saveBtn").addEventListener("click", saveSession);
    $("loadSample").addEventListener("click", loadSample);
    initCityWatcher();
    loadHistory();
  });
})();
