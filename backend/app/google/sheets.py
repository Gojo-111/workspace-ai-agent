# backend/app/google/sheets.py
import asyncio
from typing import Literal
from uuid import UUID

from googleapiclient.errors import HttpError
from sqlalchemy.ext.asyncio import AsyncSession

from app.google.client_factory import get_google_client


def _extract_sheet_values(spreadsheet: dict, sheet_id: int | None = None) -> dict:
    """
    Extract data from a spreadsheet's sheets.

    If sheet_id is provided, only that sheet is returned. Otherwise all sheets
    are extracted.
    """
    sheets_data = []
    all_sheets = spreadsheet.get("sheets", [])

    for sheet in all_sheets:
        properties = sheet.get("properties", {})
        current_sheet_id = properties.get("sheetId")

        # Skip if we're filtering and this isn't the right sheet
        if sheet_id is not None and current_sheet_id != sheet_id:
            continue

        # Extract cell data from the sheet
        grid_props = properties.get("gridProperties", {})
        row_count = grid_props.get("rowCount", 0)
        column_count = grid_props.get("columnCount", 0)

        # Get the actual cell data if available
        data = sheet.get("data", [])
        rows = []

        if data and "rowData" in data[0]:
            for row_data in data[0].get("rowData", []):
                row_cells = []
                for cell in row_data.get("values", []):
                    # Try to get the effective value, falling back to displayed string
                    value = None
                    if "userEnteredValue" in cell:
                        value = list(cell["userEnteredValue"].values())[0]
                    elif "effectiveValue" in cell:
                        value = list(cell["effectiveValue"].values())[0]
                    elif "formattedValue" in cell:
                        value = cell["formattedValue"]

                    row_cells.append(value)
                rows.append(row_cells)

        sheets_data.append(
            {
                "sheet_id": current_sheet_id,
                "title": properties.get("title", ""),
                "row_count": row_count,
                "column_count": column_count,
                "rows": rows,
            }
        )

        # If we were filtering, break after finding our sheet
        if sheet_id is not None:
            break

    return {
        "sheets": sheets_data,
    }


def _parse_range_notation(range_str: str) -> tuple[str, str | None, str | None, str | None, str | None]:
    """
    Parse a Google Sheets range notation like "Sheet1!A1:B2" or "A1:B2".
    Returns (sheet_name, start_column, start_row, end_column, end_row).
    """
    sheet_name = None
    start_col = None
    start_row = None
    end_col = None
    end_row = None

    # Split on ! to separate sheet name from range
    if "!" in range_str:
        sheet_part, range_part = range_str.split("!", 1)
        sheet_name = sheet_part.strip()
        # Remove quotes if present
        if sheet_name.startswith("'") and sheet_name.endswith("'"):
            sheet_name = sheet_name[1:-1]
    else:
        range_part = range_str

    # Parse the A1 notation
    if ":" in range_part:
        start, end = range_part.split(":", 1)
        # Parse start
        start_col = "".join(c for c in start if c.isalpha())
        start_row = "".join(c for c in start if c.isdigit())
        # Parse end
        end_col = "".join(c for c in end if c.isalpha())
        end_row = "".join(c for c in end if c.isdigit())
    else:
        # Single cell
        start_col = "".join(c for c in range_part if c.isalpha())
        start_row = "".join(c for c in range_part if c.isdigit())

    return sheet_name, start_col, start_row, end_col, end_row


async def get(
    db: AsyncSession,
    user_id: UUID,
    spreadsheet_id: str,
    range: str | None = None,
) -> dict:
    """
    Fetch a Google Sheet's data.

    If range is provided, only that range is returned. Otherwise the entire
    spreadsheet is returned.
    """
    client = await get_google_client(db, user_id, "sheets", "v4")

    def _get() -> dict:
        if range:
            return (
                client.spreadsheets()
                .values()
                .get(
                    spreadsheetId=spreadsheet_id,
                    range=range,
                )
                .execute()
            )
        else:
            return (
                client.spreadsheets()
                .get(
                    spreadsheetId=spreadsheet_id,
                    includeGridData=True,
                )
                .execute()
            )

    try:
        result = await asyncio.to_thread(_get)

        if range:
            # If we asked for a specific range, format it consistently
            values = result.get("values", [])
            return {
                "spreadsheet_id": spreadsheet_id,
                "range": range,
                "values": values,
                "row_count": len(values),
                "column_count": max((len(row) for row in values), default=0),
            }
        else:
            # Full spreadsheet
            spreadsheet_data = _extract_sheet_values(result)
            return {
                "spreadsheet_id": spreadsheet_id,
                "title": result.get("properties", {}).get("title", ""),
                "sheets": spreadsheet_data["sheets"],
            }

    except HttpError as exc:
        if exc.resp.status == 404:
            raise ValueError(f"Google Sheet not found: {spreadsheet_id}") from exc
        raise


async def create(
    db: AsyncSession,
    user_id: UUID,
    title: str,
    headers: list[str] | None = None,
    rows: list[list] | None = None,
) -> dict:
    """
    Create a new Google Sheet.

    If headers or rows are provided, they're written to the first sheet.
    """
    client = await get_google_client(db, user_id, "sheets", "v4")

    def _create() -> dict:
        return (
            client.spreadsheets()
            .create(body={"properties": {"title": title}})
            .execute()
        )

    spreadsheet = await asyncio.to_thread(_create)
    spreadsheet_id = spreadsheet["spreadsheetId"]

    # Write data if provided
    if headers or rows:
        values = []
        if headers:
            values.append(headers)
        if rows:
            values.extend(rows)

        if values:
            def _update() -> dict:
                return (
                    client.spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=spreadsheet_id,
                        range="A1",
                        body={"values": values},
                        valueInputOption="RAW",
                    )
                    .execute()
                )

            await asyncio.to_thread(_update)

    return {
        "spreadsheet_id": spreadsheet_id,
        "title": title,
    }


UpdateMode = Literal[
    "cell",
    "range",
    "append",
    "formula",
]

async def update(
    db: AsyncSession,
    user_id: UUID,
    spreadsheet_id: str,
    values: list[list],
    range: str | None = None,
    mode: UpdateMode = "range",
    sheet_name: str | None = None,
) -> dict:
    """
    Update a Google Sheet's content.

    Modes:
    - "range": replace the specified range with the given values.
    - "cell": update a single cell (range should be e.g. "A1").
    - "append": add rows to the end of the sheet.
    - "formula": write formulas to cells (values should contain formula strings).
    """
    client = await get_google_client(db, user_id, "sheets", "v4")

    if mode == "append":
        if range is not None:
            # Parse the range to get the sheet name
            parsed_sheet_name, _, _, _, _ = _parse_range_notation(range)
            actual_range = f"{parsed_sheet_name or sheet_name or 'Sheet1'}"
        else:
            actual_range = sheet_name or "Sheet1"

        def _append() -> dict:
            return (
                client.spreadsheets()
                .values()
                .append(
                    spreadsheetId=spreadsheet_id,
                    range=actual_range,
                    body={"values": values},
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                )
                .execute()
            )

        try:
            result = await asyncio.to_thread(_append)
            return {
                "spreadsheet_id": spreadsheet_id,
                "mode": mode,
                "range": actual_range,
                "updated_range": result.get("updates", {}).get("updatedRange"),
                "updated_rows": result.get("updates", {}).get("updatedRows", 0),
            }
        except HttpError as exc:
            if exc.resp.status == 404:
                raise ValueError(f"Google Sheet not found: {spreadsheet_id}") from exc
            raise

    # For non-append modes, we need a range
    if range is None:
        raise ValueError("range is required for mode 'range', 'cell', or 'formula'")

    value_input_option = "FORMULA" if mode == "formula" else "USER_ENTERED"

    def _update() -> dict:
        return (
            client.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range,
                body={"values": values},
                valueInputOption=value_input_option,
            )
            .execute()
        )

    try:
        result = await asyncio.to_thread(_update)
        return {
            "spreadsheet_id": spreadsheet_id,
            "mode": mode,
            "range": range,
            "updated_range": result.get("updatedRange"),
            "updated_rows": result.get("updatedRows", 0),
            "updated_cells": result.get("updatedCells", 0),
            "updated_columns": result.get("updatedColumns", 0),
        }
    except HttpError as exc:
        if exc.resp.status == 404:
            raise ValueError(f"Google Sheet not found: {spreadsheet_id}") from exc
        raise


async def analyze(
    db: AsyncSession,
    user_id: UUID,
    spreadsheet_id: str,
    range: str,
) -> dict:
    """
    Analyze a range of cells in a Google Sheet.

    Returns summary statistics: column types, null counts, and numeric summaries
    for numeric columns (min, max, average, sum).
    """
    # First, get the data
    sheet_data = await get(db, user_id, spreadsheet_id, range)
    values = sheet_data.get("values", [])

    if not values:
        return {
            "spreadsheet_id": spreadsheet_id,
            "range": range,
            "row_count": 0,
            "column_count": 0,
            "columns": [],
        }

    # Transpose to get columns
    max_cols = max((len(row) for row in values), default=0)
    columns = []
    for col_idx in range(max_cols):
        column_values = []
        for row in values:
            if col_idx < len(row):
                column_values.append(row[col_idx])
            else:
                column_values.append(None)
        columns.append(column_values)

    # Analyze each column
    analysis = []
    for col_idx, col_values in enumerate(columns):
        # Count non-null values
        non_null = [v for v in col_values if v is not None and v != ""]
        null_count = len(col_values) - len(non_null)

        # Determine if column is numeric
        numeric_values = []
        for v in non_null:
            try:
                # Try to convert to float
                if isinstance(v, (int, float)):
                    numeric_values.append(float(v))
                elif isinstance(v, str):
                    # Remove currency symbols and commas
                    cleaned = v.replace("$", "").replace(",", "").strip()
                    if cleaned:
                        numeric_values.append(float(cleaned))
            except (ValueError, TypeError):
                pass

        is_numeric = len(numeric_values) > 0

        col_info = {
            "column_index": col_idx,
            "column_letter": _column_index_to_letter(col_idx),
            "null_count": null_count,
            "non_null_count": len(non_null),
            "sample_values": non_null[:5],  # First 5 non-null values
            "is_numeric": is_numeric,
        }

        if is_numeric:
            numeric_sorted = sorted(numeric_values)
            col_info.update(
                {
                    "min": min(numeric_values),
                    "max": max(numeric_values),
                    "average": sum(numeric_values) / len(numeric_values),
                    "sum": sum(numeric_values),
                    "median": numeric_sorted[len(numeric_sorted) // 2],
                    "count": len(numeric_values),
                }
            )

        # Detect if this looks like a header row (text in first row, not numeric)
        if col_idx == 0 and len(non_null) > 0:
            first_value = non_null[0]
            if isinstance(first_value, str) and not first_value.isdigit():
                # This could be a header row indicator
                col_info["is_header_like"] = True

        analysis.append(col_info)

    return {
        "spreadsheet_id": spreadsheet_id,
        "range": range,
        "row_count": len(values),
        "column_count": max_cols,
        "columns": analysis,
    }


def _column_index_to_letter(index: int) -> str:
    """Convert a 0-based column index to a letter (A, B, C, ... Z, AA, AB, ...)."""
    result = ""
    n = index
    while n >= 0:
        result = chr(n % 26 + ord('A')) + result
        n = n // 26 - 1
    return result