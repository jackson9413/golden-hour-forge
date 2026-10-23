"""Solar + lunar event math for golden-hour-forge.

Pure Python, no API keys, no network calls.

Solar position uses the standard Meeus low-precision formulation, which is
accurate to roughly 0.01-0.02 degrees of altitude -- far tighter than the
minute-level planning this tool needs.  Instead of solving closed-form
sunrise/sunset equations (which break in polar latitudes), we sample the sun's
altitude across the local day and find the threshold crossings by linear
interpolation.  That handles polar day, polar night, and every twilight
definition without special-casing.
"""

from __future__ import annotations

import math
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone

try:  # pragma: no cover - stdlib on 3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


DEG = math.pi / 180.0

# Altitude thresholds (degrees above the horizon).
SUN_RISE_ALT = -0.833   # upper limb of the disk, refracted
CIVIL_ALT = -6.0
NAUTICAL_ALT = -12.0
ASTRONOMICAL_ALT = -18.0
GOLDEN_HIGH = 6.0       # top of golden hour
GOLDEN_LOW = -4.0       # bottom of golden hour / top of blue hour
BLUE_LOW = -6.0         # bottom of blue hour
NIGHT_ALT = -12.0

J2000 = 2451545.0
SYNODIC_MONTH = 29.53058867
KNOWN_NEW_MOON = 2451550.1   # 2000-01-06 18:14 UT


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def parse_date(value):
    """Accept a YYYY-MM-DD string or a date object; return a date object."""
    if isinstance(value, date_cls):
        return value
    text = str(value or "").strip()
    if not text:
        return date_cls.today()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError("Unrecognised date: " + repr(value))


def tz_offset_hours(day, tz_name):
    """UTC offset in hours for the given local calendar date (DST aware)."""
    if tz_name and ZoneInfo is not None:
        try:
            noon = datetime(day.year, day.month, day.day, 12, 0,
                            tzinfo=ZoneInfo(tz_name))
            return noon.utcoffset().total_seconds() / 3600.0
        except Exception:
            pass
    return 0.0


def julian_from_utc(dt):
    return dt.timestamp() / 86400.0 + 2440587.5


def hhmm(dt):
    return dt.strftime("%H:%M")


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def to_local(dt, tz_name):
    """Convert a UTC-aware datetime into the requested local timezone."""
    if dt is None:
        return None
    if tz_name and ZoneInfo is not None:
        try:
            return dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            pass
    return dt


# --------------------------------------------------------------------------
# solar position
# --------------------------------------------------------------------------

def solar_position(jd, lat_deg, lon_deg):
    """Return (altitude_deg, azimuth_deg) for a Julian day and observer."""
    d = jd - J2000

    g_deg = 357.529 + 0.98560028 * d
    q_deg = 280.459 + 0.98564736 * d
    g = g_deg * DEG
    l = (q_deg + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) * DEG
    e = (23.439 - 0.00000036 * d) * DEG

    ra = math.atan2(math.cos(e) * math.sin(l), math.cos(l))
    dec = math.asin(math.sin(e) * math.sin(l))

    gmst_hours = (18.697374558 + 24.06570982441908 * d) % 24.0
    lmst_hours = (gmst_hours + lon_deg / 15.0) % 24.0
    ha = (lmst_hours * 15.0 - math.degrees(ra)) * DEG

    lat = lat_deg * DEG
    alt = math.asin(math.sin(lat) * math.sin(dec)
                    + math.cos(lat) * math.cos(dec) * math.cos(ha))
    az = math.atan2(-math.sin(ha),
                    math.cos(lat) * math.tan(dec) - math.sin(lat) * math.cos(ha))
    return math.degrees(alt), math.degrees(az) % 360.0


def _elevation_series(day, lat, lon, tz_name, step_minutes=1):
    """Sample sun altitude across the whole local day."""
    offset = tz_offset_hours(day, tz_name)
    local_midnight_utc = datetime(day.year, day.month, day.day,
                                   tzinfo=timezone.utc) - timedelta(hours=offset)
    series = []
    minutes = int(24 * 60 / step_minutes)
    for i in range(minutes + 1):
        minutes_in = i * step_minutes
        dt = local_midnight_utc + timedelta(minutes=minutes_in)
        alt, _az = solar_position(julian_from_utc(dt), lat, lon)
        series.append((minutes_in, alt))
    return series, local_midnight_utc


def _crossings(series, threshold):
    """Return a list of (minute_float, direction) altitude crossings."""
    out = []
    for i in range(len(series) - 1):
        m0, a0 = series[i]
        m1, a1 = series[i + 1]
        if a0 == a1:
            continue
        if (a0 - threshold) * (a1 - threshold) < 0:
            frac = (threshold - a0) / (a1 - a0)
            out.append((m0 + frac * (m1 - m0), 1 if a1 > a0 else -1))
    return out


def _event(series, local_midnight_utc, threshold, direction):
    """Return a datetime for the first crossing in the requested direction."""
    for minute, direction_found in _crossings(series, threshold):
        if direction_found == direction:
            return local_midnight_utc + timedelta(minutes=minute)
    return None


def _window(series, local_midnight_utc, lower, upper):
    """Window between an upward lower-threshold crossing and an upward upper one."""
    for m_lo, d_lo in _crossings(series, lower):
        if d_lo != 1:
            continue
        for m_hi, d_hi in _crossings(series, upper):
            if d_hi == 1 and m_hi > m_lo:
                return (local_midnight_utc + timedelta(minutes=m_lo),
                        local_midnight_utc + timedelta(minutes=m_hi))
    return None


def _window_fall(series, local_midnight_utc, upper, lower):
    """Window between a downward upper-threshold crossing and a downward lower one."""
    for m_up, d_up in _crossings(series, upper):
        if d_up != -1:
            continue
        for m_lo, d_lo in _crossings(series, lower):
            if d_lo == -1 and m_lo > m_up:
                return (local_midnight_utc + timedelta(minutes=m_up),
                        local_midnight_utc + timedelta(minutes=m_lo))
    return None


# --------------------------------------------------------------------------
# moon
# --------------------------------------------------------------------------

def moon_phase(jd):
    """Approximate lunar phase: name, illumination fraction, age in days."""
    days = jd - KNOWN_NEW_MOON
    age = days % SYNODIC_MONTH
    frac = age / SYNODIC_MONTH
    illum = (1 - math.cos(2 * math.pi * frac)) / 2.0
    if frac < 0.03 or frac > 0.97:
        name = "New Moon"
    elif frac < 0.22:
        name = "Waxing Crescent"
    elif frac < 0.28:
        name = "First Quarter"
    elif frac < 0.47:
        name = "Waxing Gibbous"
    elif frac < 0.53:
        name = "Full Moon"
    elif frac < 0.72:
        name = "Waning Gibbous"
    elif frac < 0.78:
        name = "Last Quarter"
    else:
        name = "Waning Crescent"
    return {
        "phase": name,
        "illumination_pct": round(illum * 100, 1),
        "age_days": round(age, 1),
        "waxing": frac < 0.5,
    }


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def compute_day(day, lat, lon, tz_name="UTC"):
    """Full solar and lunar picture for one local calendar day."""
    day = parse_date(day)
    series, midnight = _elevation_series(day, lat, lon, tz_name, step_minutes=1)

    sunrise = _event(series, midnight, SUN_RISE_ALT, 1)
    sunset = _event(series, midnight, SUN_RISE_ALT, -1)
    civil_dawn = _event(series, midnight, CIVIL_ALT, 1)
    civil_dusk = _event(series, midnight, CIVIL_ALT, -1)
    nautical_dawn = _event(series, midnight, NAUTICAL_ALT, 1)
    nautical_dusk = _event(series, midnight, NAUTICAL_ALT, -1)
    astro_dawn = _event(series, midnight, ASTRONOMICAL_ALT, 1)
    astro_dusk = _event(series, midnight, ASTRONOMICAL_ALT, -1)

    golden_am = _window(series, midnight, GOLDEN_LOW, GOLDEN_HIGH)
    golden_pm = _window_fall(series, midnight, GOLDEN_HIGH, GOLDEN_LOW)
    blue_am = _window(series, midnight, BLUE_LOW, GOLDEN_LOW)
    blue_pm = _window_fall(series, midnight, GOLDEN_LOW, BLUE_LOW)

    noon_minute, noon_alt = max(series, key=lambda s: s[1])
    solar_noon = midnight + timedelta(minutes=noon_minute)

    polar = "none"
    if sunrise is None and sunset is None:
        polar = "polar_night" if noon_alt < SUN_RISE_ALT else "polar_day"
    elif sunrise is None or sunset is None:
        polar = "partial"

    def fmt(dt):
        return _fmt(to_local(dt, tz_name)) if dt else None

    def mins(a, b):
        if not a or not b:
            return None
        return round((b - a).total_seconds() / 60.0, 1)

    jd_midnight = julian_from_utc(midnight + timedelta(hours=12))

    timeline = []
    for i in range(0, 24 * 60 + 1, 10):
        dt = midnight + timedelta(minutes=i)
        alt, _ = solar_position(julian_from_utc(dt), lat, lon)
        local_dt = to_local(dt, tz_name) or dt
        timeline.append({"time": local_dt.strftime("%H:%M"), "minutes": i,
                         "altitude": round(alt, 2)})

    return {
        "date": day.isoformat(),
        "timezone": tz_name or "UTC",
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "sunrise": fmt(sunrise),
        "sunset": fmt(sunset),
        "solar_noon": fmt(solar_noon),
        "solar_noon_altitude": round(noon_alt, 2),
        "civil_dawn": fmt(civil_dawn),
        "civil_dusk": fmt(civil_dusk),
        "nautical_dawn": fmt(nautical_dawn),
        "nautical_dusk": fmt(nautical_dusk),
        "astronomical_dawn": fmt(astro_dawn),
        "astronomical_dusk": fmt(astro_dusk),
        "golden_hour_morning": {
            "start": fmt(golden_am[0]) if golden_am else None,
            "end": fmt(golden_am[1]) if golden_am else None,
            "minutes": mins(golden_am[0], golden_am[1]) if golden_am else None,
        },
        "golden_hour_evening": {
            "start": fmt(golden_pm[0]) if golden_pm else None,
            "end": fmt(golden_pm[1]) if golden_pm else None,
            "minutes": mins(golden_pm[0], golden_pm[1]) if golden_pm else None,
        },
        "blue_hour_morning": {
            "start": fmt(blue_am[0]) if blue_am else None,
            "end": fmt(blue_am[1]) if blue_am else None,
            "minutes": mins(blue_am[0], blue_am[1]) if blue_am else None,
        },
        "blue_hour_evening": {
            "start": fmt(blue_pm[0]) if blue_pm else None,
            "end": fmt(blue_pm[1]) if blue_pm else None,
            "minutes": mins(blue_pm[0], blue_pm[1]) if blue_pm else None,
        },
        "day_length_minutes": mins(sunrise, sunset),
        "polar": polar,
        "moon": moon_phase(jd_midnight),
        "timeline": timeline,
    }


def minutes_of_day(hhmm_str):
    """Convert a HH:MM string to minutes past midnight. None when unparseable."""
    try:
        parts = str(hhmm_str or "").strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return None


def windows_for_scene(day_info):
    """Named shooting windows as (start_minute, end_minute) tuples."""
    out = {}
    for key in ("golden_hour_morning", "golden_hour_evening",
                "blue_hour_morning", "blue_hour_evening"):
        block = day_info.get(key) or {}
        if block.get("start"):
            out[key] = (minutes_of_day(block["start"][11:16]),
                        minutes_of_day(block["end"][11:16]))
    return out
