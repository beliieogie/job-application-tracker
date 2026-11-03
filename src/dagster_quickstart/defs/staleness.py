from datetime import date, datetime
from dagster_quickstart.defs.sheets import get_sheet

STALE_DAYS_THRESHOLD = 10  # ~1.5 weeks


def check_stale_applications(worksheet):
    rows = worksheet.get_all_records()
    today = date.today()

    for i, row in enumerate(rows, start=2):  # row 2 = first data row (row 1 is headers)
        # Only touch rows with a genuinely blank Result. Never overwrite anything,
        # including a previous "no reply", since a real result should always win
        if row["Result"]:
            continue

        app_date_str = str(row["Application Date"]).strip()
        if not app_date_str:
            continue

        try:
            app_date = datetime.strptime(app_date_str, "%m/%d/%Y").date()
        except ValueError:
            print(f"Skipping row {i} ({row['Company']}): unreadable date {app_date_str!r}")
            continue

        days_since = (today - app_date).days

        if days_since >= STALE_DAYS_THRESHOLD:
            worksheet.update(f"C{i}", [["no reply"]], value_input_option="USER_ENTERED")
            print(f"Marked row {i} ({row['Company']}) as 'no reply' ({days_since} days since applying)")


if __name__ == "__main__":
    ws = get_sheet()
    check_stale_applications(ws)