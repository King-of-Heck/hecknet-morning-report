"""
weather_receipt.py
------------------
Morning Report
"""

import io
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
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def extract_slot(data, hour):
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


def fetch_aww_image():
    headers = {"User-Agent": "weather-receipt/1.0"}
    try:
        r = requests.get(
            "https://www.reddit.com/r/aww/top.json?limit=25&t=day",
            headers=headers, timeout=15,
        )
        r.raise_for_status()
        posts = r.json()["data"]["children"]
    except Exception as e:
        print(f"Warning: could not fetch r/aww posts — {e}")
        return None, None

    image_exts = (".jpg", ".jpeg", ".png")
    for post in posts:
        d   = post["data"]
        url = d.get("url", "")

        if url.lower().endswith(image_exts):
            img_url = url
        elif "i.redd.it" in url:
            img_url = url
        elif d.get("preview"):
            try:
                img_url = d["preview"]["images"][0]["source"]["url"].replace("&amp;", "&")
            except (KeyError, IndexError):
                continue
        else:
            continue

        try:
            ir = requests.get(img_url, headers=headers, timeout=15)
            ir.raise_for_status()
            img = Image.open(io.BytesIO(ir.content)).convert("RGB")
            return d.get("title", "r/aww"), img
        except Exception:
            continue

    return None, None


def fetch_wnn_story():
    """
    Fetches the most recently published story from World Nuclear News RSS feed.
    Returns (title, summary) or (None, None) on failure.
    """
    import xml.etree.ElementTree as ET
    try:
        r = requests.get(
            "https://world-nuclear-news.org/rss",
            headers={"User-Agent": "weather-receipt/1.0"},
            timeout=15,
        )
        r.raise_for_status()
        root = ET.fromstring(r.content)
        item = root.find(".//item")
        if item is None:
            return None, None
        title   = (item.findtext("title") or "").strip()
        summary = (item.findtext("description") or "").strip()
        import re
        summary = re.sub(r"<[^>]+>", "", summary).strip()
        return title, summary
    except Exception as e:
        print(f"Warning: could not fetch WNN story — {e}")
        return None, None


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


def prepare_aww_image(pil_img, width_px=TEXT_PX):
    """
    Resize, boost contrast + sharpness, then Floyd-Steinberg dither to
    pure black/white. Produces a crisp newspaper-dot look on thermal paper.
    """
    w, h = pil_img.size
    new_h = int(h * width_px / w)
    img   = pil_img.resize((width_px, new_h), Image.LANCZOS).convert("L")
    img   = ImageEnhance.Contrast(img).enhance(2.0)
    img   = ImageEnhance.Sharpness(img).enhance(2.0)
    img   = img.convert("1", dither=Image.FLOYDSTEINBERG)
    return img.convert("RGB")


def load_font(bold=False):
    """Load font at RENDER_SCALE * FONT_SIZE for supersampled rendering."""
    path = FONT_BOLD if bold else FONT_PATH
    try:
        return ImageFont.truetype(path, FONT_SIZE * RENDER_SCALE)
    except OSError:
        return ImageFont.load_default()

def build_receipt_image(morning, noon, evening, aww_title, aww_pil, now, printed, wnn_title=None, wnn_summary=None, jays_game=None):
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

    DIVIDER = "─" * int(text_w / (FONT_SIZE * S * 0.62))

    ops = []
    def add(text, bold=False, align="left"):
        ops.append((text, font_b if bold else font_n, align))
    def div():
        add(DIVIDER)

    add("HECKNET",        bold=True,  align="center")
    add("MORNING REPORT",  bold=True,  align="center")
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
        add(f"  {slot['condition']}")
        add(f"  Temp:   {slot['temp']}\u00b0C  (feels {slot['feels']}\u00b0C)")
        add(f"  Precip: {slot['precip']}% chance")
        div()

    if wnn_title:
        div()
        add("NUCLEAR NEWS", bold=True, align="center")
        words = wnn_title.split()
        line, wrapped = "", []
        for word in words:
            test = (line + " " + word).strip()
            if font_n.getlength(test) <= text_w:
                line = test
            else:
                if line:
                    wrapped.append(line)
                line = word
        if line:
            wrapped.append(line)
        for wl in wrapped:
            add(wl, bold=True)
        if wnn_summary:
            add("")  # spacer line
            words = wnn_summary.split()
            line, wrapped = "", []
            for word in words:
                test = (line + " " + word).strip()
                if font_n.getlength(test) <= text_w:
                    line = test
                else:
                    if line:
                        wrapped.append(line)
                    line = word
            if line:
                wrapped.append(line)
            for wl in wrapped:
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

    aww_img_prepared = None
    if aww_pil:
        div()
        add("TODAY'S AWW", bold=True, align="center")
        words = aww_title.split()
        line, wrapped = "", []
        for word in words:
            test = (line + " " + word).strip()
            if font_n.getlength(test) <= text_w:
                line = test
            else:
                if line:
                    wrapped.append(line)
                line = word
        if line:
            wrapped.append(line)
        for wl in wrapped:
            add(wl, align="center")
        aww_img_prepared = prepare_aww_image(aww_pil, width_px=TEXT_PX)


    aww_hi_h = (aww_img_prepared.size[1] * S + line_h) if aww_img_prepared else 0
    total_h  = len(ops) * line_h + aww_hi_h + line_h * 3

    hi_res = Image.new("RGB", (paper_w, total_h), "white")
    draw   = ImageDraw.Draw(hi_res)
    y      = margin // 2

    for text, font, align in ops:
        if align == "center":
            tw = font.getlength(text)
            x  = (paper_w - tw) / 2
        else:
            x = margin
        draw.text((x, y), text, font=font, fill="black")
        y += line_h

    aww_paste_y_hires = y  # where the image goes in hi-res coords

    out_w  = PAPER_PX
    out_h  = int(total_h / S)
    output = hi_res.resize((out_w, out_h), Image.LANCZOS)

    output = ImageEnhance.Contrast(output).enhance(2.5)
    output = output.convert("L").convert("RGB")

    if aww_img_prepared:
        paste_y_out = int(aww_paste_y_hires / S)
        x_out = (PAPER_PX - aww_img_prepared.width) // 2
        output.paste(aww_img_prepared, (x_out, paste_y_out))

    footer_font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    footer_text = "Knock 'em Dead King!"
    draw_out = ImageDraw.Draw(output)
    if aww_img_prepared:
        footer_y = int(aww_paste_y_hires / S) + aww_img_prepared.size[1] + 4
    else:
        footer_y = int(y / S) + 4
    tw = footer_font.getlength(footer_text)
    footer_x = (PAPER_PX - tw) / 2
    draw_out.text((footer_x, footer_y), footer_text, font=footer_font, fill="black")

    footer_line_h = FONT_SIZE + 8
    if aww_img_prepared:
        final_h = int(aww_paste_y_hires / S) + aww_img_prepared.size[1] + footer_line_h * 2
    else:
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


def print_receipt():
    print("Fetching weather...")
    data    = fetch_weather()
    morning = extract_slot(data, MORNING_HOUR)
    noon    = extract_slot(data, NOON_HOUR)
    evening = extract_slot(data, EVENING_HOUR)

    print("Fetching WNN story...")
    wnn_title, wnn_summary = fetch_wnn_story()

    print("Fetching Blue Jays game...")
    jays_game = fetch_jays_game()

    print("Fetching r/aww image...")
    aww_title, aww_pil = fetch_aww_image()

    now     = datetime.now().strftime("%A, %B %d %Y")
    printed = datetime.now().strftime("Printed %I:%M %p")

    print("Rendering receipt...")
    receipt_img = build_receipt_image(morning, noon, evening, aww_title, aww_pil, now, printed, wnn_title, wnn_summary, jays_game)

    print("Sending to printer...")
    send_image_to_printer(receipt_img)


if __name__ == "__main__":
    try:
        print_receipt()
        print("Receipt printed successfully.")
    except Exception as e:
        import os, traceback
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weather_receipt_error.log")
        with open(log_path, "a") as f:
            f.write(f"\n[{datetime.now()}] ERROR:\n{traceback.format_exc()}\n")
        raise


# TASK SCHEDULER SETUP (Windows — run once to register)
#
