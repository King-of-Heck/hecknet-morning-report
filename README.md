# Morning Report

Morning weather, nuclear news, Blue Jays and first-meeting receipt for an XP-80C thermal printer.

Prints one receipt each morning covering:

- three weather slots for the day, from Open-Meteo
- the latest World Nuclear News story, scraped from their homepage
- today's Blue Jays fixture
- the first meeting on the work calendar

## The calendar section

This is the only part that needs anything set up beyond the printer. The work
calendar is not read directly. A Power Automate flow sends a 7:15 AM email
containing the day's agenda as JSON, that mail is filtered into a Gmail label,
and the script fetches it over IMAP at print time.

You will need:

- a Power Automate flow that mails the agenda as JSON to your Gmail address
- a Gmail filter putting it under a dedicated label
- a Gmail app password saved as `gmail_app_password.txt` next to the script

Set `WORK_SENDER`, `AGENDA_SUBJECT_PREFIX`, `GMAIL_ADDRESS` and `GMAIL_LABEL`
to match. If you do not want this section, leave `GMAIL_ADDRESS` blank and the
script skips it.

Note that `GMAIL_TRASH_FOLDER` is locale-dependent. Some accounts name it
`[Gmail]/Bin` rather than `[Gmail]/Trash`; check with an IMAP LIST if the
cleanup step fails.

## Checking it without printing

    python morning_report.py --preview        writes receipt_preview.png
    python morning_report.py --meeting-test   prints the agenda fetch to console

## Tests

Stdlib unittest, no runner to install. The hardware and network modules are
stubbed only if they fail to import, so this runs on the printer machine and
off it alike.

    python -m unittest discover -s tests

## Requirements

- Windows. Printing goes through the Win32 GDI API.
- Python 3.10 or later.
- An 80mm thermal printer installed as a Windows printer. Built against an
  XP-80C at 203 DPI; other 80mm printers should work if the DPI matches.

```bash
pip install -r requirements.txt
```

Set `PRINTER_NAME` in `morning_report.py` to the printer's name as it appears in
Settings > Printers & scanners.

Receipts are rendered as images at 4x and downsampled before printing, which
is what keeps the text dark and legible on a thermal head. Courier is used
throughout; glyphs Courier lacks are composited from Segoe UI Emoji.

## Running

```bash
python morning_report.py
```

## Versioning

Tagged releases, with the change notes in [CHANGELOG.md](CHANGELOG.md).

## Licence

MIT. See [LICENSE](LICENSE).
