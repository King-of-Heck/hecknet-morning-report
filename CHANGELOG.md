# Changelog

Version numbers were reassigned for release (the old scheme bumped the
minor version for bugfixes); the original number is in parentheses. The
notes below are from each script's own version history.

## 2.1.0  (originally 1.12)

Adds FIRST MEETING section: work Outlook calendar → Power Automate 7:15 AM email
(JSON agenda) → Gmail label → IMAP fetch at print time. New fetch_first_meeting()
+ config block; --meeting-test flag (console check, no printing) and --preview
flag (renders receipt_preview.png instead of printing); word-wrap logic extracted
into _wrap() helper.

## 2.0.0  (originally 1.11)

Removed r/aww image fetch and rendering entirely (Reddit's public JSON endpoint
has been blocking these requests with 403s for a while and the feature was dead
weight). Receipt now ends after the Blue Jays section / footer.

## 1.6.2  (originally 1.10)

Fixed UnicodeEncodeError when piped through HeckNet Manager (Windows cp1252 can't
encode emoji). Added sys.stdout.reconfigure(UTF-8) and -u unbuffered flag support
so poll output streams in real time.

## 1.6.1  (originally 1.9)

Weather fetch failures are now non-fatal. If all retries are exhausted (e.g. Open-
Meteo 502), fetch_weather() returns None instead of raising, and the receipt still
prints with "Weather temporarily unavailable" shown for the three time slots. The
rest of the receipt (WNN, Jays) is unaffected. Retry wait bumped from 60s to 90s
for better 5xx recovery.

## 1.6.0  (originally 1.8)

Replaced WNN RSS feed fetch with homepage scraper. RSS feed was being served
stale/cached by WNN's CDN regardless of cache-busting headers. Now scrapes <a
class="news_box_link"> anchors from the homepage directly, which bypasses the
cache and returns current articles. Summary is fetched by following the article
link and pulling the first <p> from the body.

## 1.5.3  (originally 1.7.3)

Cache-busting query parameter and no-cache headers on the feed request.

## 1.5.2  (originally 1.7.2)

Feed diagnostics to trace why the de-duplication comparison was failing.

## 1.5.1  (originally 1.7.1)

Fixed URL normalisation in WNN seen-check. Feed URLs varied between www./non-www.
and single/double slashes, causing the comparison to never match. Now strips www.,
lowercases, and collapses double slashes before comparing.

## 1.5.0  (originally 1.7)

WNN fetch now skips already-seen stories. Last printed story URL is persisted to
wnn_last_seen.json next to the script so repeats don't occur across days. Falls
back gracefully if the file is missing.

## 1.4.0  (originally 1.6)

Added 💀 skull emoji flanking HECKNET header and ☢ radioactivity symbols flanking
NUCLEAR NEWS heading. Both use Segoe UI Emoji (seguiemj.ttf) rendered separately
and composited onto the line since Courier lacks these glyphs. SKULL_Y_OFFSET and
RADS_Y_OFFSET tune vertical alignment; SKULL_FONT_SIZE and RADS_FONT_SIZE tune
size independently.

## 1.3.0  (originally 1.5)

Added retry loop for weather fetch (handles 502 / DNS errors).

## 1.2.3  (originally 1.4)

Fixed "Knock 'em Dead King!" footer not appearing (canvas too small; now allocates
footer row before image is created).

## 1.2.2  (originally 1.3.1)

further refinements to location of farewell message.

## 1.2.1  (originally 1.3)

Change header to HeckNet - and rejigs some of the headings and location of the
farewell message.

## 1.2.0  (originally 1.2)

Adds Blue Jays Game Section

## 1.1.0  (originally 1.1)

Removes double cutting function and adds Nuclear News

## 1.0.0  (originally 1.0)

First Version

