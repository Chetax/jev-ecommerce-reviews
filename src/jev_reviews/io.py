"""Read reviews from / write decisions to CSV or Google Sheets.

Input columns: review_id, text, and optionally gold labels
(topic, sentiment, defect, refund_request).
"""

from __future__ import annotations

import csv
from pathlib import Path

from .config import Settings
from .schema import Review, parse_bool


def _row_to_review(row: dict) -> Review | None:
    text = (row.get("text") or row.get("review") or "").strip()
    if not text:
        return None
    return Review(
        review_id=str(row.get("review_id") or row.get("id") or "").strip(),
        text=text,
        topic=(row.get("topic") or "").strip().lower() or None,
        sentiment=(row.get("sentiment") or "").strip().lower() or None,
        defect=parse_bool(row.get("defect")),
        refund_request=parse_bool(row.get("refund_request")),
    )


def _rows_to_reviews(rows) -> list[Review]:
    reviews = []
    for i, row in enumerate(rows, start=1):
        r = _row_to_review(row)
        if r is None:
            continue
        if not r.review_id:
            r.review_id = f"row-{i}"
        reviews.append(r)
    return reviews


def read_csv(path: str | Path) -> list[Review]:
    with open(path, newline="", encoding="utf-8") as f:
        return _rows_to_reviews(csv.DictReader(f))


def write_csv(path: str | Path, rows: list[dict]) -> None:
    if not rows:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _open_sheet(settings: Settings):
    try:
        import gspread
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("Install Sheets support: pip install -e '.[sheets]'") from e
    if not settings.sheet_id:
        raise RuntimeError("SHEET_ID is not set.")
    gc = gspread.service_account(filename=settings.service_account_file)
    return gc.open_by_key(settings.sheet_id)


def read_sheet(settings: Settings) -> list[Review]:
    ws = _open_sheet(settings).worksheet(settings.sheet_input_tab)
    return _rows_to_reviews(ws.get_all_records())


def write_sheet(settings: Settings, rows: list[dict]) -> None:
    if not rows:
        return
    import gspread

    sh = _open_sheet(settings)
    try:
        ws = sh.worksheet(settings.sheet_output_tab)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(settings.sheet_output_tab, rows=len(rows) + 1, cols=len(rows[0]))
    header = list(rows[0].keys())
    values = [header] + [[_cell(r[h]) for h in header] for r in rows]
    ws.update(values, "A1")


def _cell(v):
    return v if isinstance(v, (int, float, str)) and not isinstance(v, bool) else str(v)
