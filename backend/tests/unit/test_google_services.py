# backend/tests/unit/test_google_services.py
"""
Unit tests for the Google service layer (drive, docs, sheets, gmail).

All external network calls are mocked. We verify that each wrapper:
- Calls the correct underlying Google API method with the right arguments.
- Handles 404 (Not Found) by raising a ValueError with a friendly message.
- Handles other HttpErrors by re-raising them (so the caller can decide).
"""

import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from googleapiclient.errors import HttpError

from app.google.drive import search as drive_search, get_file as drive_get_file
from app.google.docs import get as docs_get, create as docs_create, update as docs_update
from app.google.sheets import get as sheets_get, create as sheets_create, update as sheets_update, analyze as sheets_analyze
from app.google.gmail import search as gmail_search, get as gmail_get, create_draft, send_draft, send_message


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
def mock_db():
    """A dummy AsyncSession – not actually used because we mock get_google_client."""
    return MagicMock()


# -------------------------------------------------------------------------
# Drive tests
# -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drive_search_success(mock_db, user_id):
    with patch("app.google.drive.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.files().list().execute.return_value = {
            "files": [
                {"id": "file1", "name": "resume.pdf", "mimeType": "application/pdf"},
                {"id": "file2", "name": "cover.docx", "mimeType": "application/docx"},
            ]
        }
        mock_get_client.return_value = mock_client

        result = await drive_search(mock_db, user_id, "resume", page_size=2)

        assert result == [
            {"id": "file1", "name": "resume.pdf", "mimeType": "application/pdf"},
            {"id": "file2", "name": "cover.docx", "mimeType": "application/docx"},
        ]
        mock_client.files().list.assert_called_once_with(
            q="name contains 'resume' and trashed = false",
            pageSize=2,
            fields="files(id,name,mimeType,webViewLink,modifiedTime)",
        )


@pytest.mark.asyncio
async def test_drive_get_file_success(mock_db, user_id):
    with patch("app.google.drive.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.files().get().execute.return_value = {
            "id": "file123",
            "name": "project_plan.gsheet",
            "mimeType": "application/vnd.google-apps.spreadsheet",
        }
        mock_get_client.return_value = mock_client

        result = await drive_get_file(mock_db, user_id, "file123")

        assert result["id"] == "file123"
        assert result["name"] == "project_plan.gsheet"
        mock_client.files().get.assert_called_once_with(
            fileId="file123",
            fields="id,name,mimeType,webViewLink,modifiedTime",
        )


@pytest.mark.asyncio
async def test_drive_get_file_not_found(mock_db, user_id):
    with patch("app.google.drive.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        # Simulate a 404 HttpError
        error = HttpError(resp=MagicMock(status=404), content=b'Not Found')
        mock_client.files().get().execute.side_effect = error
        mock_get_client.return_value = mock_client

        with pytest.raises(ValueError, match="Drive file not found: missing123"):
            await drive_get_file(mock_db, user_id, "missing123")


@pytest.mark.asyncio
async def test_drive_get_file_permission_denied(mock_db, user_id):
    with patch("app.google.drive.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        # Simulate a 403 HttpError (forbidden)
        error = HttpError(resp=MagicMock(status=403), content=b'Forbidden')
        mock_client.files().get().execute.side_effect = error
        mock_get_client.return_value = mock_client

        with pytest.raises(HttpError):
            await drive_get_file(mock_db, user_id, "forbidden_file")


# -------------------------------------------------------------------------
# Docs tests
# -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_docs_get_success(mock_db, user_id):
    with patch("app.google.docs.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.documents().get().execute.return_value = {
            "documentId": "doc123",
            "title": "My Doc",
            "body": {
                "content": [
                    {"paragraph": {"elements": [{"textRun": {"content": "Hello "}}]}},
                    {"paragraph": {"elements": [{"textRun": {"content": "World!"}}]}},
                ]
            },
        }
        mock_get_client.return_value = mock_client

        result = await docs_get(mock_db, user_id, "doc123")

        assert result["document_id"] == "doc123"
        assert result["title"] == "My Doc"
        assert result["content"] == "Hello World!"
        mock_client.documents().get.assert_called_once_with(documentId="doc123")


@pytest.mark.asyncio
async def test_docs_get_not_found(mock_db, user_id):
    with patch("app.google.docs.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        error = HttpError(resp=MagicMock(status=404), content=b'Not Found')
        mock_client.documents().get().execute.side_effect = error
        mock_get_client.return_value = mock_client

        with pytest.raises(ValueError, match="Google Doc not found: missing_doc"):
            await docs_get(mock_db, user_id, "missing_doc")


@pytest.mark.asyncio
async def test_docs_create_success(mock_db, user_id):
    with patch("app.google.docs.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.documents().create().execute.return_value = {
            "documentId": "new_doc_123",
            "title": "Test Doc",
        }
        mock_get_client.return_value = mock_client

        result = await docs_create(mock_db, user_id, "Test Doc", content="Initial content")

        assert result["document_id"] == "new_doc_123"
        assert result["title"] == "Test Doc"
        mock_client.documents().create.assert_called_once_with(body={"title": "Test Doc"})
        # Also verify the insertText request was made (if content provided)
        mock_client.documents().batchUpdate.assert_called_once()
        batch_call_args = mock_client.documents().batchUpdate.call_args
        assert batch_call_args[1]["documentId"] == "new_doc_123"
        requests = batch_call_args[1]["body"]["requests"]
        assert requests[0]["insertText"]["location"]["index"] == 1
        assert requests[0]["insertText"]["text"] == "Initial content"


@pytest.mark.asyncio
async def test_docs_update_append(mock_db, user_id):
    with patch("app.google.docs.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        # First call: get document to find end index
        mock_client.documents().get().execute.return_value = {
            "documentId": "doc123",
            "body": {"content": [{"endIndex": 10}]},
        }
        mock_get_client.return_value = mock_client

        result = await docs_update(mock_db, user_id, "doc123", " appended", mode="append")

        assert result["document_id"] == "doc123"
        assert result["mode"] == "append"
        # Verify batchUpdate was called with insertText at the end
        mock_client.documents().batchUpdate.assert_called_once()
        args = mock_client.documents().batchUpdate.call_args
        requests = args[1]["body"]["requests"]
        assert requests[0]["insertText"]["location"]["index"] == 9  # endIndex-1
        assert requests[0]["insertText"]["text"] == " appended"


@pytest.mark.asyncio
async def test_docs_update_replace_paragraph(mock_db, user_id):
    with patch("app.google.docs.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        # Simulate document with two paragraphs
        mock_client.documents().get().execute.return_value = {
            "documentId": "doc123",
            "body": {
                "content": [
                    {"startIndex": 1, "endIndex": 5, "paragraph": {}},
                    {"startIndex": 5, "endIndex": 10, "paragraph": {}},
                ]
            },
        }
        mock_get_client.return_value = mock_client

        await docs_update(mock_db, user_id, "doc123", "new text", mode="replace_paragraph", paragraph_number=2)

        # It should delete the content of paragraph 2 (from startIndex to endIndex-1)
        # and insert the new text at startIndex
        batch_call = mock_client.documents().batchUpdate.call_args
        requests = batch_call[1]["body"]["requests"]
        # We expect deleteContentRange for the paragraph's text (excluding trailing newline)
        assert requests[0]["deleteContentRange"]["range"]["startIndex"] == 5
        assert requests[0]["deleteContentRange"]["range"]["endIndex"] == 9  # endIndex-1
        assert requests[1]["insertText"]["location"]["index"] == 5
        assert requests[1]["insertText"]["text"] == "new text"


# -------------------------------------------------------------------------
# Sheets tests
# -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sheets_get_success(mock_db, user_id):
    with patch("app.google.sheets.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.spreadsheets().values().get().execute.return_value = {
            "values": [["Name", "Age"], ["Alice", 30], ["Bob", 25]]
        }
        mock_get_client.return_value = mock_client

        result = await sheets_get(mock_db, user_id, "sheet123", range="A1:B3")

        assert result["spreadsheet_id"] == "sheet123"
        assert result["range"] == "A1:B3"
        assert result["values"] == [["Name", "Age"], ["Alice", 30], ["Bob", 25]]
        mock_client.spreadsheets().values().get.assert_called_once_with(
            spreadsheetId="sheet123",
            range="A1:B3",
        )


@pytest.mark.asyncio
async def test_sheets_create_success(mock_db, user_id):
    with patch("app.google.sheets.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.spreadsheets().create().execute.return_value = {
            "spreadsheetId": "new_sheet_123",
            "properties": {"title": "Test Sheet"},
        }
        mock_get_client.return_value = mock_client

        result = await sheets_create(mock_db, user_id, "Test Sheet", headers=["Col1", "Col2"], rows=[["val1", "val2"]])

        assert result["spreadsheet_id"] == "new_sheet_123"
        assert result["title"] == "Test Sheet"
        mock_client.spreadsheets().create.assert_called_once_with(
            body={"properties": {"title": "Test Sheet"}}
        )
        # Check that values.update was called with the headers+rows
        mock_client.spreadsheets().values().update.assert_called_once_with(
            spreadsheetId="new_sheet_123",
            range="A1",
            body={"values": [["Col1", "Col2"], ["val1", "val2"]]},
            valueInputOption="RAW",
        )


@pytest.mark.asyncio
async def test_sheets_update_range_success(mock_db, user_id):
    with patch("app.google.sheets.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.spreadsheets().values().update().execute.return_value = {
            "updatedRange": "A1:B2",
            "updatedRows": 2,
            "updatedColumns": 2,
            "updatedCells": 4,
        }
        mock_get_client.return_value = mock_client

        result = await sheets_update(
            mock_db, user_id, "sheet123", [["x", "y"], ["z", "w"]],
            range="A1:B2", mode="range"
        )

        assert result["spreadsheet_id"] == "sheet123"
        assert result["mode"] == "range"
        assert result["updated_range"] == "A1:B2"
        mock_client.spreadsheets().values().update.assert_called_once_with(
            spreadsheetId="sheet123",
            range="A1:B2",
            body={"values": [["x", "y"], ["z", "w"]]},
            valueInputOption="USER_ENTERED",
        )


@pytest.mark.asyncio
async def test_sheets_update_append_success(mock_db, user_id):
    with patch("app.google.sheets.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.spreadsheets().values().append().execute.return_value = {
            "updates": {"updatedRange": "Sheet1!A3", "updatedRows": 1}
        }
        mock_get_client.return_value = mock_client

        result = await sheets_update(
            mock_db, user_id, "sheet123", [["newrow"]],
            sheet_name="Sheet1", mode="append"
        )

        assert result["mode"] == "append"
        mock_client.spreadsheets().values().append.assert_called_once_with(
            spreadsheetId="sheet123",
            range="Sheet1",
            body={"values": [["newrow"]]},
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
        )


@pytest.mark.asyncio
async def test_sheets_analyze_success(mock_db, user_id):
    with patch("app.google.sheets.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        # We mock the client's values().get() directly.
        mock_client.spreadsheets().values().get().execute.return_value = {
            "values": [["Name", "Age", "Score"], ["Alice", 30, 85.5], ["Bob", 25, 90.0], ["Charlie", "N/A", 78]]
        }
        mock_get_client.return_value = mock_client

        result = await sheets_analyze(mock_db, user_id, "sheet123", "A1:C4")

        assert result["spreadsheet_id"] == "sheet123"
        assert result["range"] == "A1:C4"
        assert result["row_count"] == 3  # data rows
        assert result["column_count"] == 3

        # Check columns analysis: column 2 (Age) should have numeric analysis for rows with numbers
        # We'll just check that the response has the right structure
        columns = result["columns"]
        assert len(columns) == 3

        # Column 1 (Name) is not numeric
        assert columns[0]["is_numeric"] is False
        # Column 2 (Age) has two numeric values (30, 25) and one null
        assert columns[1]["is_numeric"] is True
        assert columns[1]["min"] == 25
        assert columns[1]["max"] == 30
        assert columns[1]["count"] == 2


@pytest.mark.asyncio
async def test_sheets_get_not_found(mock_db, user_id):
    with patch("app.google.sheets.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        error = HttpError(resp=MagicMock(status=404), content=b'Not Found')
        mock_client.spreadsheets().values().get().execute.side_effect = error
        mock_get_client.return_value = mock_client

        with pytest.raises(ValueError, match="Google Sheet not found: missing_sheet"):
            await sheets_get(mock_db, user_id, "missing_sheet", range="A1")


# -------------------------------------------------------------------------
# Gmail tests
# -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gmail_search_success(mock_db, user_id):
    with patch("app.google.gmail.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg1", "threadId": "th1"}, {"id": "msg2", "threadId": "th2"}]
        }
        mock_get_client.return_value = mock_client

        result = await gmail_search(mock_db, user_id, "from:john", max_results=5)

        assert result == [{"id": "msg1", "threadId": "th1"}, {"id": "msg2", "threadId": "th2"}]
        mock_client.users().messages().list.assert_called_once_with(
            userId="me",
            q="from:john",
            maxResults=5,
        )


@pytest.mark.asyncio
async def test_gmail_get_success(mock_db, user_id):
    with patch("app.google.gmail.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.users().messages().get().execute.return_value = {
            "id": "msg123",
            "threadId": "th123",
            "snippet": "Hello world",
        }
        mock_get_client.return_value = mock_client

        result = await gmail_get(mock_db, user_id, "msg123")

        assert result["id"] == "msg123"
        assert result["threadId"] == "th123"
        mock_client.users().messages().get.assert_called_once_with(
            userId="me",
            id="msg123",
            format="full",
        )


@pytest.mark.asyncio
async def test_gmail_create_draft_success(mock_db, user_id):
    with patch("app.google.gmail.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.users().drafts().create().execute.return_value = {
            "id": "draft456",
            "message": {"id": "msg456", "threadId": "th456"},
        }
        mock_get_client.return_value = mock_client

        result = await create_draft(mock_db, user_id, "test@example.com", "Subject", "Body")

        assert result["draft_id"] == "draft456"
        assert result["message_id"] == "msg456"
        assert result["thread_id"] == "th456"
        mock_client.users().drafts().create.assert_called_once()
        # Check that the raw message is in the body
        call_args = mock_client.users().drafts().create.call_args
        assert call_args[1]["userId"] == "me"
        body = call_args[1]["body"]
        assert "message" in body
        assert "raw" in body["message"]


@pytest.mark.asyncio
async def test_gmail_send_draft_success(mock_db, user_id):
    with patch("app.google.gmail.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.users().drafts().send().execute.return_value = {
            "id": "sent789",
            "threadId": "th789",
        }
        mock_get_client.return_value = mock_client

        result = await send_draft(mock_db, user_id, "draft456")

        assert result["message_id"] == "sent789"
        assert result["thread_id"] == "th789"
        mock_client.users().drafts().send.assert_called_once_with(
            userId="me",
            body={"id": "draft456"},
        )


@pytest.mark.asyncio
async def test_gmail_send_message_success(mock_db, user_id):
    with patch("app.google.gmail.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.users().messages().send().execute.return_value = {
            "id": "sent999",
            "threadId": "th999",
        }
        mock_get_client.return_value = mock_client

        result = await send_message(mock_db, user_id, "test@example.com", "Subject", "Body")

        assert result["message_id"] == "sent999"
        assert result["thread_id"] == "th999"
        mock_client.users().messages().send.assert_called_once()
        call_args = mock_client.users().messages().send.call_args
        assert call_args[1]["userId"] == "me"
        body = call_args[1]["body"]
        assert "raw" in body


@pytest.mark.asyncio
async def test_gmail_create_draft_not_found(mock_db, user_id):
    # If Gmail service is unavailable, it could return 404 or something.
    # We'll test that it raises ValueError on 404 (which we treat as service unavailable)
    with patch("app.google.gmail.get_google_client") as mock_get_client:
        mock_client = MagicMock()
        error = HttpError(resp=MagicMock(status=404), content=b'Not Found')
        mock_client.users().drafts().create().execute.side_effect = error
        mock_get_client.return_value = mock_client

        with pytest.raises(ValueError, match="Gmail service not available"):
            await create_draft(mock_db, user_id, "test@example.com", "Subject", "Body")