# Job Application Tracker

A Dagster pipeline that reads job application emails from Gmail and keeps a Google Sheet up to date: new applications get a row, replies update the row's status, and silent applications get marked "no reply" after ten days.

Built because tracking a job search by hand stops happening about two weeks in.

## What it does

Three assets run in order:

| Asset                     | What it does                                                                                                                         |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `new_job_applications`    | Scans the last 30 days of Gmail for application confirmations, extracts the company name, appends a row with the email's actual date |
| `result_updates`          | Re-scans per company, classifies replies as `phone screen` / `rejected` / `offer`, writes to the Result column                       |
| `stale_application_check` | Marks applications with no reply after 10 days, without overwriting a real result                                                    |

The sheet has these columns: `Company`, `Application Date`, `Result`, `Status`, `Contact`, `Contact Title`, `Domain`.

## The interesting part: extracting a company name

This is most of the work. "Thank you for applying" emails come from shared ATS platforms, so the sender domain is usually `greenhouse-mail.io` or `ashbyhq.com` rather than the employer. `extract_company_name()` tries several sources in order and returns `(company, is_reliable)`, where an unreliable result is logged instead of written:

1. **Blocked senders.** Job boards, aggregators and sales outreach (`scale.jobs`, `theladders.com`, `upwork.com`) are never an employer and are rejected outright. The domain is the signal here, because the display name is whichever person or brand the platform happens to send as.
2. **Explicit overrides.** A small domain-to-name map for senders where no rule gets it right: `pmc.com` is Penske Media Corp, `macysandbloomingdalesjobs.com` is Macy's. These names appear only in the body or not at all.
3. **Subject line first, for iCIMS senders**, whose display name is often a parent company (`PUBLICISGROUPE` for an Epsilon role).
4. **The local part of the address**, for platforms that send from `<company>@domain`: `quickbase@myworkday.com`, `hyland+autoreply@talent.icims.com`.
5. **The first domain label**, for platforms that send from `<company>.<platform>`: `sunday.teamtailor-mail.com`.
6. **The sender's display name**, with noise words stripped (`Talent`, `Team`, `Hiring`), trailing platform suffixes removed (`Cadent, LLC @ icims`), and multi-brand lists reduced to the first brand (`Jobs at Macy's, Bluemercury and Bloomingdale's`). Skipped entirely for personal domains and for platforms that put the recruiter's own name there.
7. **Subject line patterns**, covering "applying to X", "application at X", "application with X", and "X | ...".
8. **Domain root**, as a last resort, flagged unreliable when the domain is a shared ATS.

Duplicates are caught two ways: a normalized name key (so "Gusto, Inc." and "Gusto" match), and the sender's own domain, which catches the case where one company sends differently worded subjects ("Alpaca Markets" in one email, "Alpaca" in the next). Shared ATS domains are excluded from the domain check, since dozens of employers send from the same one.

## Classifying replies

`classify_email()` returns `offer`, `phone screen`, `rejected`, or `None`.

Offers and interview requests are read from the subject only, because bodies are too noisy: confirmation emails routinely say "next steps". Rejections check the body too, since many arrive with a neutral subject like "Thank you for your application". Rejection is tested before interview, so an "Update on your interview" subject with a rejection body lands correctly.

Body phrases are chosen to avoid false positives on confirmations. "were not selected" is in the list; plain "not selected" is not, because confirmations say "if you are not selected to move forward".

## Setup

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

### Google credentials

Three APIs need to be enabled in a Google Cloud project: **Gmail API**, **Sheets API**, and **Drive API** (the Drive API is required because `gspread` opens the sheet by name).

**Gmail (OAuth, read-only).** Create an OAuth client ID of type "Desktop app", download the JSON, and save it as `src/dagster_quickstart/defs/credentials.json`. The first run opens a browser for consent and writes `token.json` beside it.

**Sheets (service account).** Create a service account, download its key as `src/dagster_quickstart/defs/service_account.json`, and share your sheet with the service account's email address as an Editor.

All three JSON files are gitignored.

### Environment

Create a `.env` in the project root:

```
JOB_TRACKER_EXCLUDE_NAMES=your name,yourname,surname
JOB_TRACKER_SHEET=name of your google sheet
```

`JOB_TRACKER_EXCLUDE_NAMES` is a comma-separated list of names that should never be treated as a company. Your own name belongs here: it leaks in from reply threads where the only machine-readable name is yours.

### Running

```bash
uv run dagster dev
```

Open http://localhost:3000 and materialize the assets. A schedule is defined for 9:30 AM every other day; it ships disabled.

To exercise the classifier without touching Gmail or the sheet:

```bash
uv run python -m dagster_quickstart.defs.classifier
```

## Known limitations

- **No company name in the email.** Some recruiters write from a personal or company address with the employer's name only in a logo image. Nothing text-based recovers that, so those are logged as low confidence and skipped rather than guessed at.
- **Rows are append-only.** The pipeline never edits or deletes a company name, so a bad row has to be removed by hand. Fixing a name in the code prevents recurrence; it does not repair history.
- **New ATS platforms need adding.** Each platform has its own convention for where the employer's name lives. An unrecognized one usually falls through to the domain root and gets flagged unreliable, which is the intended failure: a skipped row beats a wrong one.
- **OAuth tokens expire** roughly weekly while the Google Cloud app is in "Testing" publishing status. Delete `token.json` and re-run to re-authenticate.
- **Gmail has a per-minute quota.** Requests back off and retry rather than failing the run, so a large sheet makes `result_updates` slow rather than broken.
- **Date formatting uses `%-m/%-d/%Y`**, which is Linux and macOS only. On Windows use `%#m/%#d/%Y`.

## Project layout

```
src/dagster_quickstart/defs/
├── gmail.py               # OAuth, search, message body extraction
├── sheets.py              # Service account auth, worksheet access
├── classifier.py          # Company name extraction and reply classification
├── staleness.py           # "no reply" after 10 days
└── job_tracker_assets.py  # The three Dagster assets, the job, the schedule
```
