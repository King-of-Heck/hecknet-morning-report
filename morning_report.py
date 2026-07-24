"""
Morning report receipt.

Prints a single receipt each morning: three weather slots for today, the
latest World Nuclear News story, the Blue Jays fixture, and the first meeting
on the work calendar.

    python morning_report.py                 print it
    python morning_report.py --preview       render receipt_preview.png instead
    python morning_report.py --meeting-test  check the calendar fetch only
"""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import io
import json
import os
import time
import requests
import win32print
import win32ui
from datetime import datetime, date
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter, ImageWin


PRINTER_NAME = "XP-80C"

# Font — any TTF installed on your PC.
# "cour.ttf"   = Courier New  |  "consola.ttf" = Consolas  |  "lucon.ttf" = Lucida Console
FONT_PATH    = "cour.ttf"
FONT_BOLD    = "courbd.ttf"
FONT_SIZE    = 32          # pt — adjust to taste

RENDER_SCALE = 4

PRINTER_DPI  = 203
PAPER_MM     = 80
PAPER_PX     = int(PAPER_MM / 25.4 * PRINTER_DPI)   # ≈ 638 px at output res
MARGIN_PX    = 10
TEXT_PX      = PAPER_PX - 2 * MARGIN_PX

LATITUDE     = 43.6532
LONGITUDE    = -79.3832
TIMEZONE     = "America/Toronto"

WEATHER_RETRY_ATTEMPTS = 3    # how many times to try before giving up
WEATHER_RETRY_WAIT     = 90   # seconds to wait between attempts

WORK_SENDER             = "work.sender@example.com"   # From: address the flow sends as
AGENDA_SUBJECT_PREFIX   = "HECKNET-AGENDA"
GMAIL_ADDRESS           = "you@example.com"
GMAIL_LABEL             = "MorningReport"
GMAIL_TRASH_FOLDER      = "[Gmail]/Bin"   # this account's locale names it "Bin", not "Trash" — verified via IMAP LIST
GMAIL_APP_PASSWORD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gmail_app_password.txt")

MORNING_HOUR = 8
NOON_HOUR    = 12
EVENING_HOUR = 18


WMO_CODES = {
    0:  "Clear sky",
    1:  "Mainly clear",        2:  "Partly cloudy",    3:  "Overcast",
    45: "Foggy",               48: "Icy fog",
    51: "Light drizzle",       53: "Drizzle",          55: "Heavy drizzle",
    61: "Light rain",          63: "Rain",              65: "Heavy rain",
    71: "Light snow",          73: "Snow",              75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers",       81: "Showers",           82: "Heavy showers",
    85: "Light snow showers",  86: "Snow showers",
    95: "Thunderstorm",        96: "Thunderstorm w/ hail", 99: "Heavy thunderstorm",
}

def describe(code):
    return WMO_CODES.get(code, f"Code {code}")


def fetch_weather():
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":           LATITUDE,
        "longitude":          LONGITUDE,
        "hourly":             "temperature_2m,apparent_temperature,precipitation_probability,weathercode",
        "temperature_unit":   "celsius",
        "wind_speed_unit":    "kmh",
        "precipitation_unit": "mm",
        "timezone":           TIMEZONE,
        "forecast_days":      1,
    }
    last_error = None
    for attempt in range(1, WEATHER_RETRY_ATTEMPTS + 1):
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_error = e
            if attempt < WEATHER_RETRY_ATTEMPTS:
                print(f"  Weather fetch failed (attempt {attempt}/{WEATHER_RETRY_ATTEMPTS}): {e}")
                print(f"  Retrying in {WEATHER_RETRY_WAIT}s...")
                time.sleep(WEATHER_RETRY_WAIT)
            else:
                print(f"  Weather fetch failed after {WEATHER_RETRY_ATTEMPTS} attempts: {e}")
                print(f"  Continuing without weather data.")
    return None  # non-fatal — receipt still prints without weather

def extract_slot(data, hour):
    if data is None:
        return {"temp": None, "feels": None, "precip": None, "condition": None}
    times = data["hourly"]["time"]
    # Use the date from the first timestamp in the API response
    # to avoid any local date / timezone mismatch
    today = times[0][:10]
    target = f"{today}T{hour:02d}:00"
    if target in times:
        idx = times.index(target)
    else:
        today_times = [t for t in times if t.startswith(today)]
        if not today_times:
            raise ValueError(f"No forecast data found for today ({today})")
        idx = times.index(min(today_times, key=lambda t: abs(int(t[11:13]) - hour)))
    return {
        "temp":      round(data["hourly"]["temperature_2m"][idx]),
        "feels":     round(data["hourly"]["apparent_temperature"][idx]),
        "precip":    data["hourly"]["precipitation_probability"][idx],
        "condition": describe(data["hourly"]["weathercode"][idx]),
    }


_WNN_SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wnn_last_seen.json")

def _normalise_url(url: str) -> str:
    """Strip www., lowercase, and collapse double slashes in path for reliable comparison."""
    url = url.lower().strip()
    url = url.replace("://www.", "://")   # drop www.
    scheme, _, rest = url.partition("://")
    rest = rest.replace("//", "/")
    return f"{scheme}://{rest}"

def _load_wnn_seen() -> str | None:
    try:
        with open(_WNN_SEEN_FILE, "r") as f:
            return json.load(f).get("last_url")
    except Exception:
        return None

def _save_wnn_seen(url: str):
    try:
        with open(_WNN_SEEN_FILE, "w") as f:
            json.dump({"last_url": url}, f)
    except Exception as e:
        print(f"Warning: could not save WNN seen file — {e}")

def fetch_wnn_story():
    """
    Scrapes the WNN homepage for the latest unseen article, then fetches
    the article page itself to pull a summary. Bypasses the stale RSS cache.
    Returns (title, summary) or (None, None) on failure.
    """
    from bs4 import BeautifulSoup
    import re

    WNN_BASE = "https://www.world-nuclear-news.org"
    HEADERS  = {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cache-Control":   "no-cache",
    }

    last_seen_url  = _load_wnn_seen()
    last_seen_norm = _normalise_url(last_seen_url) if last_seen_url else None
    print(f"  WNN: last seen (norm) = {last_seen_norm}")

    try:
        r = requests.get(WNN_BASE + "/", headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"WNN: homepage fetch failed — {e}")
        return None, None

    soup  = BeautifulSoup(r.content, "html.parser")
    links = soup.find_all("a", class_="news_box_link")
    print(f"  WNN: {len(links)} article links found on homepage")

    chosen_url   = None
    chosen_title = None
    for a in links:
        href = a.get("href", "").strip()
        if not href.startswith("/articles/"):
            continue
        full_url  = WNN_BASE + href
        full_norm = _normalise_url(full_url)

        title_div = a.find("div", class_="news_list_title")
        title     = title_div.get_text(strip=True) if title_div else ""
        if not title:
            continue

        print(f"WNN: checking — {title[:60]}")
        if last_seen_norm and full_norm == last_seen_norm:
            print(f"  WNN: skipping already-seen story")
            continue

        chosen_url   = full_url
        chosen_title = title
        print(f"WNN: selected — {title[:60]}")
        break

    if not chosen_url:
        print("  WNN: no new stories found on homepage.")
        return None, None

    summary = ""
    try:
        ar = requests.get(chosen_url, headers=HEADERS, timeout=15)
        ar.raise_for_status()
        asoup = BeautifulSoup(ar.content, "html.parser")
        for p in asoup.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 60:   # skip tiny/empty paragraphs
                summary = text
                break
    except Exception as e:
        print(f"WNN: article fetch failed — {e}")

    _save_wnn_seen(chosen_url)
    return chosen_title, summary


def fetch_jays_game():
    """
    Fetches today's Blue Jays game from the MLB Stats API (no key required).
    Returns a dict with opponent, time_et, home_away, sp_jays, sp_opp,
    or None if no game today.
    """
    import xml.etree.ElementTree as ET
    from datetime import timezone, timedelta

    JAYS_TEAM_ID = 141
    today_str = date.today().strftime("%Y-%m-%d")

    MLB_ABBREVS = {
        108: "LAA", 109: "ARI", 110: "BAL", 111: "BOS", 112: "CHC",
        113: "CIN", 114: "CLE", 115: "COL", 116: "DET", 117: "HOU",
        118: "KC",  119: "LAD", 120: "WSH", 121: "NYM", 133: "OAK",
        134: "PIT", 135: "SD",  136: "SEA", 137: "SF",  138: "STL",
        139: "TB",  140: "TEX", 141: "TOR", 142: "MIN", 143: "PHI",
        144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
    }

    try:
        url = "https://statsapi.mlb.com/api/v1/schedule"
        params = {
            "sportId": 1,
            "teamId": JAYS_TEAM_ID,
            "date": today_str,
            "hydrate": "probablePitcher(note),team",
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        dates = data.get("dates", [])
        if not dates:
            return None
        games = dates[0].get("games", [])
        if not games:
            return None

        game = games[0]

        home_team_id = game["teams"]["home"]["team"]["id"]
        away_team_id = game["teams"]["away"]["team"]["id"]
        jays_are_home = (home_team_id == JAYS_TEAM_ID)
        opp_id   = away_team_id if jays_are_home else home_team_id
        opp_abbr = MLB_ABBREVS.get(opp_id, game["teams"]["away" if jays_are_home else "home"]["team"]["abbreviation"])
        home_away = "vs" if jays_are_home else "@"

        game_time_utc = game.get("gameDate")  # e.g. "2025-05-01T17:07:00Z"
        if game_time_utc:
            dt_utc = datetime.strptime(game_time_utc, "%Y-%m-%dT%H:%M:%SZ")
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            et_offset = timedelta(hours=-4)  # EDT (UTC-4); change to -5 for EST
            dt_et = dt_utc + et_offset
            time_et = dt_et.strftime("%I:%M %p ET").lstrip("0") or "12:00 AM ET"
        else:
            time_et = "TBD"

        def pitcher_name(side):
            pp = game["teams"][side].get("probablePitcher")
            if pp:
                return pp.get("fullName", "TBD")
            return "TBD"

        sp_jays = pitcher_name("home" if jays_are_home else "away")
        sp_opp  = pitcher_name("away" if jays_are_home else "home")

        return {
            "home_away": home_away,
            "opp_abbr":  opp_abbr,
            "time_et":   time_et,
            "sp_jays":   sp_jays,
            "sp_opp":    sp_opp,
            "double":    len(games) > 1,
        }

    except Exception as e:
        print(f"Warning: could not fetch Jays game — {e}")
        return None

# FETCH FIRST MEETING (work calendar via Gmail)
# A Power Automate flow on the work tenant emails the day's agenda as

def _html_to_text(html_body):
    """Strip tags, unescape entities, then collapse whitespace runs to a
    single space. The last step matters: Power Automate's rich-text editor
    hard-wraps long paragraphs in the raw HTML source (a real embedded
    newline, not a MIME soft line break), which is invisible once a browser
    renders it but is an unescaped control character to json.loads."""
    import re, html as html_mod
    text = html_mod.unescape(re.sub(r"<[^>]+>", " ", html_body))
    return re.sub(r"\s+", " ", text)

def _extract_agenda_json(raw_email_bytes):
    """Parse a raw RFC822 message; return the JSON agenda list from its body.
    Raises on any failure — caller decides how to degrade."""
    import email as email_mod
    msg = email_mod.message_from_bytes(raw_email_bytes)
    body = None
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_type() in ("text/html", "text/plain"):
            payload = part.get_payload(decode=True)
            if payload:
                body = payload.decode(part.get_content_charset() or "utf-8",
                                      errors="replace")
                if part.get_content_type() == "text/html":
                    break   # prefer the HTML part; keep looking if plain
    if body is None:
        raise ValueError("no text part found in agenda email")
    text  = _html_to_text(body)
    start = text.find("[")
    end   = text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("no JSON array found in agenda email body")
    return json.loads(text[start:end + 1])

def _pick_first_meeting(events, target_date):
    """Apply the exclusion rules and return the earliest remaining event on
    target_date (a "YYYY-MM-DD" string), or None. Rules: drop events not on
    target_date, all-day events, declined meetings, and solo blocks (no
    required or optional attendees). Tentative/not-responded count.
    target_date matters because the agenda email now covers a 2-day window
    (today + tomorrow) so both the morning and evening reports can read
    from the same email -- each just asks for its own day."""
    def qualifies(ev):
        if not (ev.get("start") or "").startswith(target_date):
            return False
        if ev.get("isAllDay"):
            return False
        if ev.get("response") == "declined":
            return False
        attendees = ((ev.get("requiredAttendees") or "")
                     + (ev.get("optionalAttendees") or ""))
        if not attendees.replace(";", "").strip():
            return False
        return True
    qualifying = [ev for ev in events if qualifies(ev)]
    if not qualifying:
        return None
    return min(qualifying, key=lambda ev: ev.get("start") or "~")

def _format_meeting_time(start_iso):
    """'2026-07-17T09:30:00' -> '9:30 AM'. Truncates to seconds so
    fractional-second variants from the flow can't break parsing."""
    dt = datetime.fromisoformat(start_iso[:19])
    return dt.strftime("%I:%M %p").lstrip("0")

def fetch_first_meeting():
    """
    Reads today's HECKNET-AGENDA email from the Gmail label over IMAP and
    picks the first qualifying meeting. Housekeeping: any message in the
    label whose subject is NOT today's expected subject is moved to Trash.
    Returns {"time", "subject"}, {"no_meetings": True}, or None on failure.
    All exceptions are caught — this can never kill the receipt.
    """
    import imaplib
    import email as email_mod
    try:
        with open(GMAIL_APP_PASSWORD_FILE, "r") as f:
            app_password = f.read().strip().replace(" ", "")
        expected_subject = (AGENDA_SUBJECT_PREFIX + " "
                            + date.today().strftime("%Y-%m-%d"))

        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        try:
            imap.login(GMAIL_ADDRESS, app_password)
            status, _ = imap.select(f'"{GMAIL_LABEL}"')
            if status != "OK":
                raise RuntimeError(f"could not open label {GMAIL_LABEL}")

            status, data = imap.uid(
                "SEARCH", None,
                f'(FROM "{WORK_SENDER}" SUBJECT "{expected_subject}")')
            if status != "OK":
                raise RuntimeError("IMAP search failed")
            uids       = data[0].split()
            result     = None
            agenda_raw = None
            # SEARCH matches substrings; walk newest-first and require the
            # Subject header to EQUAL the expected subject (trust rule).
            for uid in reversed(uids):
                status, msg_data = imap.uid("FETCH", uid, "(RFC822)")
                if status != "OK" or not msg_data or msg_data[0] is None:
                    raise RuntimeError("IMAP fetch failed")
                candidate = email_mod.message_from_bytes(msg_data[0][1])
                if (candidate.get("Subject") or "").strip() == expected_subject:
                    agenda_raw = msg_data[0][1]
                    break
            if agenda_raw is not None:
                events = _extract_agenda_json(agenda_raw)
                print(f"  Meeting: {len(events)} events in agenda email")
                today = date.today().strftime("%Y-%m-%d")
                first = _pick_first_meeting(events, today)
                if first is None:
                    result = {"no_meetings": True}
                else:
                    result = {"time":    _format_meeting_time(first["start"]),
                              "subject": first.get("subject") or "(no subject)"}

            # Housekeeping: trash everything that isn't today's agenda.
            # (Gmail quirk: \Deleted alone only strips the label; COPY to
            status, data = imap.uid("SEARCH", None, "ALL")
            if status == "OK":
                for uid in data[0].split():
                    s, hdr = imap.uid(
                        "FETCH", uid,
                        "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
                    if s != "OK" or not hdr or hdr[0] is None:
                        continue
                    subj = (email_mod.message_from_bytes(hdr[0][1]).get("Subject") or "").strip()
                    if subj != expected_subject:
                        imap.uid("COPY", uid, f'"{GMAIL_TRASH_FOLDER}"')
                        imap.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
                imap.expunge()
            imap.close()
        finally:
            imap.logout()

        if result is None:
            print(f"  Meeting: no email found for '{expected_subject}'")
        return result
    except Exception as e:
        print(f"  Meeting fetch failed - {e}")
        return None


def load_font(bold=False):
    """Load font at RENDER_SCALE * FONT_SIZE for supersampled rendering."""
    path = FONT_BOLD if bold else FONT_PATH
    try:
        return ImageFont.truetype(path, FONT_SIZE * RENDER_SCALE)
    except OSError:
        return ImageFont.load_default()

def _wrap(text, font, max_width):
    """Greedy word-wrap: split text into lines that each render <= max_width
    px in the given font. A single word longer than max_width is kept whole."""
    line, wrapped = "", []
    for word in text.split():
        test = (line + " " + word).strip()
        if font.getlength(test) <= max_width:
            line = test
        else:
            if line:
                wrapped.append(line)
            line = word
    if line:
        wrapped.append(line)
    return wrapped

# EMOJI GLYPH HELPERS
# Courier lacks emoji/symbol glyphs so we render them separately using

# Tune these to taste (all values are at 4x hi-res scale; divide by 4 for
# approximate printed pixels).
SKULL_FONT_SIZE = 24   # pt — size of 💀 skull glyphs
SKULL_Y_OFFSET  = 40   # px at 4x — shifts skulls DOWN relative to text baseline
RADS_FONT_SIZE  = 26   # pt — size of ☢ radioactivity glyphs
RADS_Y_OFFSET   = 36   # px at 4x — shifts rads symbol DOWN relative to text baseline

_EMOJI_FONT_CANDIDATES = [
    "seguiemj.ttf",                  # Segoe UI Emoji — ships with Windows 10+
    "C:/Windows/Fonts/seguiemj.ttf", # explicit path fallback
    "seguisym.ttf",                  # Segoe UI Symbol — older fallback (no colour emoji)
]

def _load_emoji_font(size_pt: int):
    for path in _EMOJI_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size_pt * RENDER_SCALE)
        except OSError:
            continue
    return load_font(bold=True)   # last resort: Courier (will render as box)

def _draw_flanked_header(draw, text: str, glyph: str,
                         font_text, font_glyph,
                         paper_w: int, y: int, y_offset: int):
    """
    Render  <glyph>  <text>  <glyph>  centred on the line.
    font_text is used for the label, font_glyph for the flanking symbols.
    y_offset shifts the glyphs DOWN relative to the text y so they sit level.
    """
    gap     = int(font_text.size * 0.4)
    glyph_w = int(font_glyph.getlength(glyph))
    text_w  = int(font_text.getlength(text))
    total_w = glyph_w + gap + text_w + gap + glyph_w

    x = (paper_w - total_w) // 2
    draw.text((x, y + y_offset), glyph, font=font_glyph, fill="black")
    x += glyph_w + gap
    draw.text((x, y), text, font=font_text, fill="black")
    x += text_w + gap
    draw.text((x, y + y_offset), glyph, font=font_glyph, fill="black")

def build_receipt_image(morning, noon, evening, now, printed, wnn_title=None, wnn_summary=None, jays_game=None, meeting=None):
    """
    Renders receipt at 4x resolution then downsamples to OUTPUT resolution.
    This gives much crisper, darker text than rendering at output res directly.
    """
    S        = RENDER_SCALE
    paper_w  = PAPER_PX * S
    margin   = MARGIN_PX * S
    text_w   = TEXT_PX * S
    line_h   = (FONT_SIZE + 5) * S

    font_n = load_font(bold=False)
    font_b = load_font(bold=True)

    font_skull = _load_emoji_font(SKULL_FONT_SIZE)
    font_rads  = _load_emoji_font(RADS_FONT_SIZE)

    DIVIDER = "─" * int(text_w / (FONT_SIZE * S * 0.62))

    ops = []
    def add(text, bold=False, align="left"):
        ops.append((text, font_b if bold else font_n, align))
    def div():
        add(DIVIDER)

    add("",  align="center")   # → 💀 HECKNET 💀
    add("MORNING REPORT", bold=True, align="center")
    add(now,                          align="center")
    add(printed,                      align="center")
    div()

    add("Toronto Weather", bold=True, align="center")
    div()

    for label, slot in [
        ("MORNING  (8 AM)",  morning),
        ("NOON     (12 PM)", noon),
        ("EVENING  (6 PM)",  evening),
    ]:
        add(label, bold=True)
        if slot["temp"] is None:
            add("  Weather temporarily unavailable")
        else:
            add(f"  {slot['condition']}")
            add(f"  Temp:   {slot['temp']}\u00b0C  (feels {slot['feels']}\u00b0C)")
            add(f"  Precip: {slot['precip']}% chance")
        div()

    # First meeting section — ALWAYS rendered (spec: positive confirmation;
    # a missing section and a broken pipeline must not look identical)
    add("FIRST MEETING", bold=True, align="center")
    if meeting is None:
        add("  Meeting info unavailable")
    elif meeting.get("no_meetings"):
        add("  No meetings today")
    else:
        add(f"  {meeting['time']}")
        indent_w = int(font_n.getlength("  "))
        for wl in _wrap(meeting["subject"], font_n, text_w - indent_w):
            add("  " + wl)
    div()

    nuclear_header_op_idx = None
    if wnn_title:
        nuclear_header_op_idx = len(ops)
        add("",  align="center")   # → ☢ NUCLEAR NEWS ☢
        for wl in _wrap(wnn_title, font_n, text_w):
            add(wl, bold=True)
        if wnn_summary:
            add("")  # spacer line
            for wl in _wrap(wnn_summary, font_n, text_w):
                add(wl)
        div()

    if jays_game:
        add("BLUE JAYS", bold=True, align="center")
        matchup = f"TOR {jays_game['home_away']} {jays_game['opp_abbr']}"
        add(matchup, align="center")
        add(f"  First pitch: {jays_game['time_et']}")
        add(f"  TOR: {jays_game['sp_jays']}")
        add(f"  {jays_game['opp_abbr']}: {jays_game['sp_opp']}")
        if jays_game.get("double"):
            add("  (Doubleheader today!)")
        div()
    elif jays_game is None:
        pass

    top_pad = max(SKULL_Y_OFFSET, RADS_Y_OFFSET)
    footer_line_h = FONT_SIZE + 8
    total_h  = len(ops) * line_h + line_h * 3 + footer_line_h * 2 + top_pad

    hi_res = Image.new("RGB", (paper_w, total_h), "white")
    draw   = ImageDraw.Draw(hi_res)
    y      = margin // 2 + top_pad

    for i, (text, font, align) in enumerate(ops):
        if align == "center":
            tw = font.getlength(text)
            x  = (paper_w - tw) / 2
        else:
            x = margin
        draw.text((x, y), text, font=font, fill="black")

        if i == 0:
            _draw_flanked_header(draw, "HECKNET", "\U0001F480",
                                 font_b, font_skull, paper_w, y, SKULL_Y_OFFSET)
        if nuclear_header_op_idx is not None and i == nuclear_header_op_idx:
            _draw_flanked_header(draw, "NUCLEAR NEWS", "\u2622",
                                 font_b, font_rads, paper_w, y, RADS_Y_OFFSET)

        y += line_h

    out_w  = PAPER_PX
    out_h  = int(total_h / S)
    output = hi_res.resize((out_w, out_h), Image.LANCZOS)

    output = ImageEnhance.Contrast(output).enhance(2.5)
    output = output.convert("L").convert("RGB")

    footer_font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    footer_text = "Knock 'em Dead King!"
    draw_out = ImageDraw.Draw(output)
    footer_y = int(y / S) + 4
    tw = footer_font.getlength(footer_text)
    footer_x = (PAPER_PX - tw) / 2
    draw_out.text((footer_x, footer_y), footer_text, font=footer_font, fill="black")

    final_h = int(y / S) + footer_line_h * 2
    output = output.crop((0, 0, out_w, final_h))

    return output

def send_image_to_printer(pil_img):
    """
    Send PIL image to printer via Windows GDI.
    Pre-resizes to exact printer pixel width so driver does zero scaling,
    which eliminates row-skipping artefacts.
    """
    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(PRINTER_NAME)
    printer_w = hdc.GetDeviceCaps(110)  # HORZRES

    img_w, img_h = pil_img.size
    if img_w != printer_w:
        new_h = int(img_h * printer_w / img_w)
        pil_img = pil_img.resize((printer_w, new_h), Image.LANCZOS)
        img_w, img_h = pil_img.size

    hdc.StartDoc("Weather Receipt")
    hdc.StartPage()
    dib = ImageWin.Dib(pil_img)
    dib.draw(hdc.GetHandleOutput(), (0, 0, img_w, img_h))
    hdc.EndPage()
    hdc.EndDoc()
    hdc.DeleteDC()


def print_receipt(preview=False):
    print("Fetching weather...")
    data    = fetch_weather()
    morning = extract_slot(data, MORNING_HOUR)
    noon    = extract_slot(data, NOON_HOUR)
    evening = extract_slot(data, EVENING_HOUR)

    print("Fetching WNN story...")
    wnn_title, wnn_summary = fetch_wnn_story()

    print("Fetching Blue Jays game...")
    jays_game = fetch_jays_game()

    print("Fetching first meeting...")
    meeting = fetch_first_meeting()

    now     = datetime.now().strftime("%A, %B %d %Y")
    printed = datetime.now().strftime("Printed %I:%M %p")

    print("Rendering receipt...")
    receipt_img = build_receipt_image(morning, noon, evening, now, printed,
                                      wnn_title, wnn_summary, jays_game, meeting)

    if preview:
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "receipt_preview.png")
        receipt_img.save(out)
        print(f"Preview saved to {out} (nothing sent to printer).")
    else:
        print("Sending to printer...")
        send_image_to_printer(receipt_img)


if __name__ == "__main__":
    if "--meeting-test" in sys.argv:
        print("Meeting fetch test (nothing will be printed to paper)...")
        result = fetch_first_meeting()
        if result is None:
            print("RESULT: Meeting info unavailable")
        elif result.get("no_meetings"):
            print("RESULT: No meetings today")
        else:
            print(f"RESULT: FIRST MEETING -> {result['time']} | {result['subject']}")
        sys.exit(0)
    try:
        print_receipt(preview="--preview" in sys.argv)
        print("Receipt printed successfully.")
    except Exception as e:
        import os, traceback
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weather_receipt_error.log")
        with open(log_path, "a") as f:
            f.write(f"\n[{datetime.now()}] ERROR:\n{traceback.format_exc()}\n")
        raise


# TASK SCHEDULER SETUP (Windows — run once to register)
#
