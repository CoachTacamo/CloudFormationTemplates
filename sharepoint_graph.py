"""SharePoint Graph API client for Azure GovCloud.

Wraps the Microsoft Graph API endpoints needed to list and download
files from a SharePoint document library. All endpoints target the
GovCloud Graph endpoint by default. This is Milestone 2 of the
ImportDocuments C#-to-Python conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urlparse

import requests

# GovCloud Graph API base URL (Req 6.1)
GRAPH_BASE_URL: str = "https://graph.microsoft.us/v1.0"


# ---------------------------------------------------------------------------
# Error types (Req 8.1 – 8.5)
# ---------------------------------------------------------------------------


class SharePointGraphError(Exception):
    """Base exception for Graph API HTTP errors."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


class SiteNotFoundError(SharePointGraphError):
    """Raised when site resolution returns HTTP 404."""


class DriveNotFoundError(Exception):
    """Raised when a drive name is not found in the drives list.

    This is a logical error (not an HTTP error), so it does NOT
    extend SharePointGraphError.
    """

    def __init__(self, drive_name: str) -> None:
        self.drive_name = drive_name
        super().__init__(f"Drive not found: {drive_name}")


class GraphFileNotFoundError(SharePointGraphError):
    """Raised when file download returns HTTP 404.

    Prefixed with 'Graph' to avoid shadowing the built-in
    FileNotFoundError.
    """


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DriveInfo:
    """Represents a SharePoint document library (drive)."""

    drive_id: str
    drive_name: str


@dataclass(frozen=True)
class FileItem:
    """Represents a file from a SharePoint drive listing."""

    name: str
    item_id: str
    drive_id: str
    web_url: str
    metadata: dict[str, object]


# ---------------------------------------------------------------------------
# URL converter (Req 1.1 – 1.5)
# ---------------------------------------------------------------------------


def sharepoint_url_to_graph_path(sharepoint_url: str) -> str:
    """Convert a SharePoint URL to Graph API site-addressing format.

    Args:
        sharepoint_url: URL like "https://{host}/sites/{path}"

    Returns:
        Graph site path like "{host}:/sites/{path}"

    Raises:
        ValueError: If URL is empty, None, or missing /sites/ segment.
    """
    if not sharepoint_url:
        raise ValueError("SharePoint URL must not be empty or None")

    url = sharepoint_url.rstrip("/")
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path

    sites_marker = "/sites/"
    idx = path.find(sites_marker)
    if idx == -1:
        raise ValueError(
            f"URL does not contain a /sites/ segment: {sharepoint_url}"
        )

    remainder = path[idx + len(sites_marker) :]
    return f"{host}:/sites/{remainder}"


# ---------------------------------------------------------------------------
# Graph API client (Req 6.1, 6.2, 7.1, 7.2, 7.3)
# ---------------------------------------------------------------------------


class SharePointGraphClient:
    """Microsoft Graph API client for SharePoint operations.

    Args:
        token: Bearer token string from sharepoint_auth module.
        base_url: Graph API base URL. Defaults to GRAPH_BASE_URL.
    """

    def __init__(self, token: str, base_url: str | None = None) -> None:
        self.base_url = base_url if base_url is not None else GRAPH_BASE_URL
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {token}"

    def __enter__(self) -> "SharePointGraphClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self._session.close()

    def _raise_for_graph_error(
        self, response: requests.Response, context: str = ""
    ) -> None:
        """Check response status and raise appropriate error.

        Args:
            response: The HTTP response to check.
            context: Hint for 404 mapping — ``"site"`` or ``"file"``.

        Raises:
            SiteNotFoundError: When status is 404 and context is ``"site"``.
            GraphFileNotFoundError: When status is 404 and context is ``"file"``.
            SharePointGraphError: For any other non-OK status.
        """
        if response.ok:
            return

        # Try to extract the Graph API error message from JSON body (Req 8.5)
        message = ""
        try:
            body = response.json()
            message = body.get("error", {}).get("message", "")
        except Exception:
            pass
        if not message:
            message = response.text

        status = response.status_code

        if status == 404:
            if context == "site":
                raise SiteNotFoundError(status, message)
            if context == "file":
                raise GraphFileNotFoundError(status, message)

        raise SharePointGraphError(status, message)

    # ------------------------------------------------------------------
    # Site resolution (Req 2.1 – 2.4)
    # ------------------------------------------------------------------

    def resolve_site(self, graph_site_path: str) -> str:
        """Resolve a Graph site path to a Site ID.

        Args:
            graph_site_path: Graph site path like ``host:/sites/path``.

        Returns:
            The site ID string.

        Raises:
            SiteNotFoundError: If the site does not exist (HTTP 404).
            SharePointGraphError: For other HTTP errors.
        """
        url = f"{self.base_url}/sites/{graph_site_path}"
        response = self._session.get(url)
        self._raise_for_graph_error(response, context="site")
        return response.json()["id"]

    # ------------------------------------------------------------------
    # Drive listing (Req 3.1, 3.2, 3.5)
    # ------------------------------------------------------------------

    def list_drives(self, site_id: str) -> list[DriveInfo]:
        """List all drives for a site.

        Args:
            site_id: The site ID obtained from :meth:`resolve_site`.

        Returns:
            List of DriveInfo records.

        Raises:
            SharePointGraphError: For HTTP errors.
        """
        url = f"{self.base_url}/sites/{site_id}/drives"
        response = self._session.get(url)
        self._raise_for_graph_error(response)
        return [
            DriveInfo(drive_id=d["id"], drive_name=d["name"])
            for d in response.json()["value"]
        ]

    # ------------------------------------------------------------------
    # Drive lookup by name (Req 3.3, 3.4)
    # ------------------------------------------------------------------

    def get_drive_by_name(self, site_id: str, drive_name: str) -> DriveInfo:
        """Find a drive by name within a site.

        Args:
            site_id: The site ID obtained from :meth:`resolve_site`.
            drive_name: Exact (case-sensitive) name of the drive.

        Returns:
            The matching DriveInfo record.

        Raises:
            DriveNotFoundError: If no drive matches the name.
            SharePointGraphError: For HTTP errors.
        """
        drives = self.list_drives(site_id)
        for drive in drives:
            if drive.drive_name == drive_name:
                return drive
        raise DriveNotFoundError(drive_name)

    # ------------------------------------------------------------------
    # File listing with pagination (Req 4.1 – 4.7, 6.3, 6.4)
    # ------------------------------------------------------------------

    def list_files(
        self, drive_id: str, folder_path: str = ""
    ) -> Iterator[FileItem]:
        """List files in a drive, optionally filtered to a folder.

        Yields:
            FileItem records for each file (skips folders).
            Handles pagination automatically.

        Raises:
            SharePointGraphError: For HTTP errors.
        """
        if folder_path:
            url = (
                f"{self.base_url}/drives/{drive_id}"
                f"/root:/{folder_path}:/children"
            )
        else:
            url = f"{self.base_url}/drives/{drive_id}/root/children"

        params = {"$expand": "listItem($expand=fields)"}

        while url is not None:
            response = self._session.get(url, params=params)
            self._raise_for_graph_error(response)
            data = response.json()

            for item in data.get("value", []):
                if "file" not in item:
                    continue
                yield FileItem(
                    name=item["name"],
                    item_id=item["id"],
                    drive_id=drive_id,
                    web_url=item["webUrl"],
                    metadata=item.get("listItem", {}).get("fields", {}),
                )

            url = data.get("@odata.nextLink")
            # After the first request, don't re-send query params —
            # @odata.nextLink URLs are fully-qualified (Req 6.4).
            params = None

    # ------------------------------------------------------------------
    # File download (Req 5.1 – 5.4)
    # ------------------------------------------------------------------

    def download_file(
        self, drive_id: str, item_id: str
    ) -> requests.Response:
        """Download file content as a streaming response.

        Returns:
            A requests.Response with stream=True. Caller must close it.

        Raises:
            GraphFileNotFoundError: If the file does not exist (HTTP 404).
            SharePointGraphError: For other HTTP errors.
        """
        url = f"{self.base_url}/drives/{drive_id}/items/{item_id}/content"
        response = self._session.get(url, stream=True)
        self._raise_for_graph_error(response, context="file")
        return response
