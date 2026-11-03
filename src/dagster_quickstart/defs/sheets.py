import gspread
from datetime import date

from pathlib import Path

def get_sheet():
    creds_path = Path(__file__).parent / "service_account.json"
    gc = gspread.service_account(filename=str(creds_path))

    # Replace this with your actual sheet's name exactly as it appears in Google Sheets
    sh = gc.open("jobs i've applied to")
    worksheet = sh.sheet1
    return worksheet


def read_existing_rows(worksheet):
    rows = worksheet.get_all_records()
    print(f"Found {len(rows)} existing rows:")
    for row in rows:
        print(row)
    return rows


def append_test_row(worksheet):
    # Format the date to match your sheet's existing style (e.g. 8/23/2026)
    today_str = date.today().strftime("%-m/%-d/%Y")  # Windows: use "%#m/%#d/%Y" instead

    # Test row — matches your columns: Company, Application Date, Result, Contact, Contact Title
    test_row = ["Test Company", today_str, "", "", ""]

    # USER_ENTERED makes Sheets parse the date the same way it would if you typed it manually,
    # so it becomes a real date value instead of plain text
    worksheet.append_row(test_row, value_input_option="USER_ENTERED")
    print("Appended test row.")


if __name__ == "__main__":
    ws = get_sheet()
    read_existing_rows(ws)
    append_test_row(ws)