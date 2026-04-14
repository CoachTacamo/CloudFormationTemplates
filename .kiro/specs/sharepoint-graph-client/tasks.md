# Implementation Plan: SharePoint Graph API Client

## Overview

Implement `sharepoint_graph.py` — a Python module wrapping the Microsoft Graph API for listing and downloading files from a SharePoint document library in Azure GovCloud. This is Milestone 2 of the ImportDocuments C#-to-Python conversion. The module provides a `SharePointGraphClient` class, data models (`DriveInfo`, `FileItem`), custom error types, and a pure URL converter function. All tests mock HTTP calls via `unittest.mock` — no real Graph API traffic.

## Tasks

- [x] 1. Define error types and data models
  - [x] 1.1 Create `sharepoint_graph.py` with module docstring, imports (`requests`, `dataclasses`, `typing`), and the `GRAPH_BASE_URL` constant set to `https://graph.microsoft.us/v1.0`
    - Define `SharePointGraphError(Exception)` with `status_code: int` and `message: str` attributes
    - Define `SiteNotFoundError(SharePointGraphError)` for HTTP 404 on site resolution
    - Define `DriveNotFoundError(Exception)` with `drive_name: str` attribute (not a subclass of `SharePointGraphError` — it's a logical error, not an HTTP error)
    - Define `GraphFileNotFoundError(SharePointGraphError)` for HTTP 404 on file download (prefixed with `Graph` to avoid shadowing built-in `FileNotFoundError`)
    - Define frozen `DriveInfo` dataclass with `drive_id: str` and `drive_name: str`
    - Define frozen `FileItem` dataclass with `name: str`, `item_id: str`, `drive_id: str`, `web_url: str`, `metadata: dict[str, object]`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 1.2 Write unit tests for error types and data models
    - Verify `SharePointGraphError` stores `status_code` and `message`, and is a subclass of `Exception`
    - Verify `SiteNotFoundError` is a subclass of `SharePointGraphError`
    - Verify `DriveNotFoundError` is NOT a subclass of `SharePointGraphError` and stores `drive_name`
    - Verify `GraphFileNotFoundError` is a subclass of `SharePointGraphError`
    - Verify `DriveInfo` and `FileItem` are frozen (immutable)
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 2. Implement the URL converter function
  - [x] 2.1 Implement `sharepoint_url_to_graph_path(sharepoint_url: str) -> str` as a module-level pure function
    - Validate input is non-empty and not None, raise `ValueError` if so
    - Strip trailing slash
    - Parse URL to extract host and path
    - Verify `/sites/` is present in the path, raise `ValueError` if missing
    - Return `{host}:/sites/{remainder}`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 2.2 Write property test for URL converter round-trip consistency
    - **Property: Round-trip consistency** — For all valid SharePoint URLs, converting to Graph_Site_Path and reconstructing by prepending `https://` and replacing `:/sites/` with `/sites/` SHALL produce the original URL without trailing slash
    - Use Hypothesis to generate URLs matching `https://{host}/sites/{path}` pattern
    - **Validates: Requirement 1.6**

  - [x] 2.3 Write unit tests for URL converter edge cases
    - Test valid URL conversion (e.g., `https://contoso.sharepoint.us/sites/team` → `contoso.sharepoint.us:/sites/team`)
    - Test trailing slash stripping
    - Test URLs with additional path segments after site path
    - Test `ValueError` on empty string, `None`, and URLs missing `/sites/`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 3. Implement `SharePointGraphClient` class skeleton and session management
  - [x] 3.1 Implement the `SharePointGraphClient` class with `__init__`, `__enter__`, `__exit__`, and `_raise_for_graph_error` helper
    - `__init__` accepts `token: str` and optional `base_url: str`, defaults to `GRAPH_BASE_URL`
    - Create a `requests.Session` and set `Authorization: Bearer {token}` header on it
    - `__enter__` returns `self`, `__exit__` closes the session
    - `_raise_for_graph_error` checks response status, extracts `error.message` from JSON body when available, maps HTTP 404 to appropriate `NotFound` subclass based on a context parameter
    - _Requirements: 6.1, 6.2, 7.1, 7.2, 7.3, 8.5_

  - [x] 3.2 Write unit tests for session management and auth header
    - Verify session is created with correct `Authorization` header
    - Verify context manager closes the session on exit
    - Verify default `base_url` is `https://graph.microsoft.us/v1.0`
    - Verify custom `base_url` overrides the default
    - _Requirements: 6.1, 6.2, 7.1, 7.2, 7.3_

- [x] 4. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement site resolution and drive listing
  - [x] 5.1 Implement `resolve_site(self, graph_site_path: str) -> str`
    - Send GET to `{base_url}/sites/{graph_site_path}`
    - Return the `id` field from the JSON response
    - Raise `SiteNotFoundError` on HTTP 404
    - Raise `SharePointGraphError` on other HTTP errors
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 5.2 Implement `list_drives(self, site_id: str) -> list[DriveInfo]`
    - Send GET to `{base_url}/sites/{site_id}/drives`
    - Parse `value` array and return list of `DriveInfo` records
    - Raise `SharePointGraphError` on HTTP errors
    - _Requirements: 3.1, 3.2, 3.5_

  - [x] 5.3 Implement `get_drive_by_name(self, site_id: str, drive_name: str) -> DriveInfo`
    - Call `list_drives()` and find the drive matching `drive_name` (case-sensitive)
    - Raise `DriveNotFoundError` if no match found
    - _Requirements: 3.3, 3.4_

  - [x] 5.4 Write unit tests for site resolution
    - Mock successful site resolution returning a site ID
    - Mock HTTP 404 raising `SiteNotFoundError`
    - Mock other HTTP errors raising `SharePointGraphError` with status code and message
    - Verify Authorization header is sent
    - Verify request URL starts with configured `base_url`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 6.3, 7.1_

  - [x] 5.5 Write unit tests for drive listing and lookup
    - Mock successful drive listing returning multiple drives
    - Mock `get_drive_by_name` finding the correct drive
    - Mock `get_drive_by_name` raising `DriveNotFoundError` when name not found
    - Verify drive name included in `DriveNotFoundError` message
    - Mock HTTP error raising `SharePointGraphError`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 6. Implement file listing with pagination
  - [x] 6.1 Implement `list_files(self, drive_id: str, folder_path: str = "") -> Iterator[FileItem]`
    - When `folder_path` is empty, GET `{base_url}/drives/{drive_id}/root/children` with `$expand=listItem($expand=fields)` query parameter
    - When `folder_path` is non-empty, GET `{base_url}/drives/{drive_id}/root:/{folder_path}:/children` with the same `$expand` parameter
    - Yield `FileItem` for each entry with a `file` facet; skip entries with a `folder` facet
    - Extract metadata from `listItem.fields` into `FileItem.metadata`
    - Follow `@odata.nextLink` URLs as-is for pagination until no more pages remain
    - Raise `SharePointGraphError` on HTTP errors on any page
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 6.3, 6.4_

  - [x] 6.2 Write unit tests for file listing
    - Mock single-page response with mix of files and folders, verify only files yielded
    - Mock multi-page response with `@odata.nextLink`, verify all pages consumed
    - Mock response with `listItem.fields` metadata, verify metadata extracted into `FileItem`
    - Mock empty folder (empty `value` array), verify no items yielded
    - Verify `$expand=listItem($expand=fields)` query parameter is included
    - Verify folder path URL construction for both empty and non-empty paths
    - Mock HTTP error on second page, verify `SharePointGraphError` raised
    - Verify `@odata.nextLink` URLs are followed as-is (not prefixed with base_url)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 6.3, 6.4_

- [x] 7. Implement file download
  - [x] 7.1 Implement `download_file(self, drive_id: str, item_id: str) -> requests.Response`
    - Send GET to `{base_url}/drives/{drive_id}/items/{item_id}/content` with `stream=True`
    - Return the raw `requests.Response` on success
    - Raise `GraphFileNotFoundError` on HTTP 404
    - Raise `SharePointGraphError` on other HTTP errors
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 7.2 Write unit tests for file download
    - Mock successful streaming download, verify `stream=True` is used
    - Mock HTTP 404 raising `GraphFileNotFoundError`
    - Mock other HTTP errors raising `SharePointGraphError`
    - Verify Authorization header is sent
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 8. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- All tests use `unittest.mock` to mock `requests.Session` — no real Graph API calls
- Follow the same test file conventions as `tests/test_sharepoint_auth.py` (Hypothesis + pytest)
- The module lives at the project root as `sharepoint_graph.py`, matching `sharepoint_auth.py`
- Tests go in `tests/test_sharepoint_graph.py`
- Property tests validate the URL converter's round-trip invariant; unit tests cover HTTP interactions
