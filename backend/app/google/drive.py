import asyncio
from uuid import UUID

from googleapiclient.errors import HttpError
from sqlalchemy.ext.asyncio import AsyncSession

from app.google.client_factory import get_google_client


DRIVE_FIELDS = "id,name,mimeType,webViewLink,modifiedTime"


async def search(
    db: AsyncSession,
    user_id: UUID,
    query: str,
    page_size: int = 10,
) -> list[dict]:
    """
    Search Drive for files matching a name query.

    Returns lightweight summaries (id, name, mimeType, link, last modified),
    not file content. Reading content is a separate call (docs.get /
    sheets.get) once the agent has picked a file from these results.
    """
    client = await get_google_client(db, user_id, "drive", "v3")

    # Escape single quotes so a search term can't break out of the q string.
    escaped_query = query.replace("'", "\\'")

    def _search() -> dict:
        return (
            client.files()
            .list(
                q=f"name contains '{escaped_query}' and trashed = false",
                pageSize=page_size,
                fields=f"files({DRIVE_FIELDS})",
            )
            .execute()
        )

    result = await asyncio.to_thread(_search)

    return result.get("files", [])


async def get_file(
    db: AsyncSession,
    user_id: UUID,
    file_id: str,
) -> dict:
    """
    Fetch metadata for a single Drive file by ID.

    Metadata only, this is how the agent confirms a file exists and figures
    out what it is (a Doc, a Sheet, something else) before calling the
    matching read tool.
    """
    client = await get_google_client(db, user_id, "drive", "v3")

    def _get() -> dict:
        return (
            client.files()
            .get(
                fileId=file_id,
                fields=DRIVE_FIELDS,
            )
            .execute()
        )

    try:
        return await asyncio.to_thread(_get)
    except HttpError as exc:
        if exc.resp.status == 404:
            raise ValueError(f"Drive file not found: {file_id}") from exc
        raise