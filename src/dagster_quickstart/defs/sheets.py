import os
from pathlib import Path

import gspread
from dotenv import load_dotenv

load_dotenv()

SHEET_NAME = os.getenv("JOB_TRACKER_SHEET", "job applications")


def get_sheet():
    creds_path = Path(__file__).parent / "service_account.json"
    gc = gspread.service_account(filename=str(creds_path))
    sh = gc.open(SHEET_NAME)
    return sh.sheet1


def read_existing_rows(worksheet):
    rows = worksheet.get_all_records()
    print(f"Found {len(rows)} existing rows:")
    for row in rows:
        print(row)
    return rows


if __name__ == "__main__":
    # Read-only check that auth works and the sheet is reachable.
    ws = get_sheet()
    read_existing_rows(ws)