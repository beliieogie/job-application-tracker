import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from dagster import asset, define_asset_job, ScheduleDefinition
from googleapiclient.errors import HttpError
from dagster_quickstart.defs.sheets import get_sheet
from dagster_quickstart.defs.classifier import (
    classify_email, extract_company_name, normalize_company,
    sender_domain, is_automated_domain,
)
from dagster_quickstart.defs.staleness import check_stale_applications


def execute_with_retry(request, attempts=5):
    """Gmail's per-minute quota is bursty; back off and retry instead of failing the run."""
    for n in range(attempts):
        try:
            return request.execute()
        except HttpError as e:
            if e.resp.status in (403, 429) and "ateLimit" in str(e) and n < attempts - 1:
                time.sleep(2 ** n * 5)  # 5s, 10s, 20s, 40s
                continue
            raise


@asset
def new_job_applications() -> list[dict]:
    """
    Searches Gmail for job application confirmation emails from the last 30 days,
    extracts a company name and the email's actual date for each one, adds a new
    row to the sheet for any company not already present, and returns the list found.
    """
    service = get_gmail_service()
    worksheet = get_sheet()

    existing_rows = worksheet.get_all_records()
    existing_companies = {normalize_company(row["Company"]) for row in existing_rows if row["Company"]}
    existing_domains = {row.get("Domain", "") for row in existing_rows if row.get("Domain")}

    # Widened from 1d to 30d — duplicate-checking above makes it safe to re-scan
    # a larger window each run, so gaps between runs no longer cause missed applications
    query = 'subject:(application OR "thank you for applying") newer_than:30d'
    results = execute_with_retry(service.users().messages().list(
        userId="me", q=query, maxResults=100
    ))
    messages = results.get("messages", [])

    found = []
    for msg in messages:
        msg_data = execute_with_retry(service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["Subject", "From", "Date"]
        ))

        headers = msg_data["payload"]["headers"]
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
        sender = next((h["value"] for h in headers if h["name"] == "From"), "")
        date_header = next((h["value"] for h in headers if h["name"] == "Date"), "")

        company, is_reliable = extract_company_name(subject, sender)

        found.append({"sender": sender, "subject": subject, "date": date_header, "company": company})

        if not is_reliable:
            print(f"SKIPPED (low confidence): {company!r} — subject: {subject!r}, sender: {sender!r}")
            continue

        domain = sender_domain(sender)
        own_domain = domain if domain and not is_automated_domain(sender) else ""

        if normalize_company(company) in existing_companies:
            continue
        if own_domain and own_domain in existing_domains:
            print(f"SKIPPED (domain already tracked): {company!r} via {own_domain}")
            continue

        try:
            email_date = parsedate_to_datetime(date_header)
            date_str = email_date.strftime("%-m/%-d/%Y")
        except (TypeError, ValueError):
            date_str = datetime.today().strftime("%-m/%-d/%Y")

        new_row = [company, date_str, "", "", "", "", own_domain]
        existing_companies.add(normalize_company(company))
        if own_domain:
            existing_domains.add(own_domain)
        worksheet.append_row(new_row, value_input_option="USER_ENTERED")
        print(f"Added new row: {company} (date: {date_str}, from subject: {subject!r}, sender: {sender!r})")

    return found


@asset(deps=[new_job_applications])
def result_updates() -> None:
    """
    Re-scans Gmail for result emails from companies already in the sheet,
    classifies them, and updates the matching row's Result column.
    Real results always overwrite a previous 'no reply'.
    """
    worksheet = get_sheet()
    rows = worksheet.get_all_records()

    service = get_gmail_service()

    for i, row in enumerate(rows, start=2):
        company = row["Company"]
        if not company:
            continue

        # Search Gmail for any recent email mentioning this company
        query = f'subject:"{company}" newer_than:30d'
        results = execute_with_retry(service.users().messages().list(
            userId="me", q=query, maxResults=5
        ))
        messages = results.get("messages", [])

        for msg in messages:
            # One 'full' fetch gives both headers and body, halving the quota cost
            msg_data = execute_with_retry(service.users().messages().get(
                userId="me", id=msg["id"], format="full"
            ))
            headers = msg_data["payload"]["headers"]
            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
            sender = next((h["value"] for h in headers if h["name"] == "From"), "")

            body = extract_body(msg_data)
            classification = classify_email(sender, subject, body)
            if classification:
                worksheet.update(f"C{i}", [[classification]], value_input_option="USER_ENTERED")
                print(f"Updated row {i} ({company}) -> {classification}")
                break  # stop checking more emails for this company once we find a match


@asset(deps=[result_updates])
def stale_application_check() -> None:
    """
    Marks applications with no response after 10 days as 'no reply',
    without overwriting any existing Result value.
    """
    worksheet = get_sheet()
    check_stale_applications(worksheet)


job_tracker_job = define_asset_job(
    "job_tracker_job",
    selection=["new_job_applications", "result_updates", "stale_application_check"],
)

job_tracker_schedule = ScheduleDefinition(
    job=job_tracker_job,
    cron_schedule="30 9 */2 * *",  # 9:30 AM, every other day
)
