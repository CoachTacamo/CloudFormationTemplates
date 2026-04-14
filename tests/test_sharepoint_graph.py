"""Unit tests for sharepoint_graph module — error types and data models.

Tests cover Requirements 8.1, 8.2, 8.3, 8.4.
"""

import dataclasses

import pytest

from sharepoint_graph import (
    DriveInfo,
    DriveNotFoundError,
    FileItem,
    GraphFileNotFoundError,
    SharePointGraphError,
    SiteNotFoundError,
)


# ---------------------------------------------------------------------------
# Task 1.2: Unit tests for error types and data models
# ---------------------------------------------------------------------------


class TestSharePointGraphError:
    """Verify SharePointGraphError stores status_code and message, and is a subclass of Exception.

    Validates: Requirement 8.1
    """

    def test_is_subclass_of_exception(self):
        assert issubclass(SharePointGraphError, Exception)

    def test_stores_status_code_and_message(self):
        err = SharePointGraphError(status_code=500, message="Internal Server Error")
        assert err.status_code == 500
        assert err.message == "Internal Server Error"

    def test_str_contains_status_and_message(self):
        err = SharePointGraphError(status_code=403, message="Forbidden")
        assert "403" in str(err)
        assert "Forbidden" in str(err)


class TestSiteNotFoundError:
    """Verify SiteNotFoundError is a subclass of SharePointGraphError.

    Validates: Requirement 8.2
    """

    def test_is_subclass_of_sharepoint_graph_error(self):
        assert issubclass(SiteNotFoundError, SharePointGraphError)

    def test_is_subclass_of_exception(self):
        assert issubclass(SiteNotFoundError, Exception)

    def test_can_be_raised_and_caught_as_sharepoint_graph_error(self):
        with pytest.raises(SharePointGraphError):
            raise SiteNotFoundError(status_code=404, message="Site not found")


class TestDriveNotFoundError:
    """Verify DriveNotFoundError is NOT a subclass of SharePointGraphError and stores drive_name.

    Validates: Requirement 8.3
    """

    def test_is_not_subclass_of_sharepoint_graph_error(self):
        assert not issubclass(DriveNotFoundError, SharePointGraphError)

    def test_is_subclass_of_exception(self):
        assert issubclass(DriveNotFoundError, Exception)

    def test_stores_drive_name(self):
        err = DriveNotFoundError(drive_name="Documents")
        assert err.drive_name == "Documents"

    def test_str_contains_drive_name(self):
        err = DriveNotFoundError(drive_name="Shared Files")
        assert "Shared Files" in str(err)


class TestGraphFileNotFoundError:
    """Verify GraphFileNotFoundError is a subclass of SharePointGraphError.

    Validates: Requirement 8.4
    """

    def test_is_subclass_of_sharepoint_graph_error(self):
        assert issubclass(GraphFileNotFoundError, SharePointGraphError)

    def test_is_subclass_of_exception(self):
        assert issubclass(GraphFileNotFoundError, Exception)

    def test_can_be_raised_and_caught_as_sharepoint_graph_error(self):
        with pytest.raises(SharePointGraphError):
            raise GraphFileNotFoundError(status_code=404, message="File not found")


class TestDriveInfoFrozen:
    """Verify DriveInfo is frozen (immutable).

    Validates: Requirement 8.1 (data models)
    """

    def test_is_frozen_dataclass(self):
        info = DriveInfo(drive_id="abc", drive_name="Documents")
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.drive_id = "xyz"

    def test_stores_fields(self):
        info = DriveInfo(drive_id="d1", drive_name="Library")
        assert info.drive_id == "d1"
        assert info.drive_name == "Library"


class TestFileItemFrozen:
    """Verify FileItem is frozen (immutable).

    Validates: Requirement 8.1 (data models)
    """

    def test_is_frozen_dataclass(self):
        item = FileItem(
            name="report.pdf",
            item_id="i1",
            drive_id="d1",
            web_url="https://example.com/report.pdf",
            metadata={"Author": "Alice"},
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            item.name = "other.pdf"

    def test_stores_fields(self):
        meta = {"Category": "Finance"}
        item = FileItem(
            name="budget.xlsx",
            item_id="i2",
            drive_id="d2",
            web_url="https://example.com/budget.xlsx",
            metadata=meta,
        )
        assert item.name == "budget.xlsx"
        assert item.item_id == "i2"
        assert item.drive_id == "d2"
        assert item.web_url == "https://example.com/budget.xlsx"
        assert item.metadata == {"Category": "Finance"}


# ---------------------------------------------------------------------------
# Task 2.2: Property test for URL converter round-trip consistency
# ---------------------------------------------------------------------------

from hypothesis import given, settings, strategies as st

from sharepoint_graph import sharepoint_url_to_graph_path

# Strategy: generate valid SharePoint URLs matching https://{host}/sites/{path}
# Host: non-empty DNS-like label (letters, digits, dots, hyphens)
_host_label = st.from_regex(r"[a-z][a-z0-9\-]{0,20}", fullmatch=True)
_host = st.builds(
    lambda parts: ".".join(parts),
    st.lists(_host_label, min_size=2, max_size=4),
)

# Path segments after /sites/ — at least one non-empty segment
_path_segment = st.from_regex(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,30}", fullmatch=True)
_site_path = st.builds(
    lambda parts: "/".join(parts),
    st.lists(_path_segment, min_size=1, max_size=4),
)


class TestProperty1URLConverterRoundTrip:
    """Feature: sharepoint-graph-client, Property: Round-trip consistency

    **Validates: Requirement 1.6**
    """

    @given(host=_host, site_path=_site_path)
    @settings(max_examples=200)
    def test_round_trip_consistency(self, host: str, site_path: str):
        """**Validates: Requirement 1.6**

        For all valid SharePoint URLs, converting to Graph_Site_Path and
        reconstructing by prepending `https://` and replacing `:/sites/`
        with `/sites/` SHALL produce the original URL without trailing slash.
        """
        original_url = f"https://{host}/sites/{site_path}"

        # Convert to Graph site path
        graph_path = sharepoint_url_to_graph_path(original_url)

        # Reconstruct the original URL from the graph path
        reconstructed = f"https://{graph_path.replace(':/sites/', '/sites/')}"

        assert reconstructed == original_url, (
            f"Round-trip failed:\n"
            f"  original:      {original_url}\n"
            f"  graph_path:    {graph_path}\n"
            f"  reconstructed: {reconstructed}"
        )


# ---------------------------------------------------------------------------
# Task 2.3: Unit tests for URL converter edge cases
# ---------------------------------------------------------------------------


class TestURLConverterValidConversion:
    """Verify valid SharePoint URLs are converted to Graph site paths.

    Validates: Requirements 1.1
    """

    def test_basic_url(self):
        result = sharepoint_url_to_graph_path("https://contoso.sharepoint.us/sites/team")
        assert result == "contoso.sharepoint.us:/sites/team"

    def test_commercial_domain(self):
        result = sharepoint_url_to_graph_path("https://contoso.sharepoint.com/sites/project")
        assert result == "contoso.sharepoint.com:/sites/project"


class TestURLConverterTrailingSlash:
    """Verify trailing slashes are stripped before conversion.

    Validates: Requirements 1.2
    """

    def test_single_trailing_slash(self):
        result = sharepoint_url_to_graph_path("https://contoso.sharepoint.us/sites/team/")
        assert result == "contoso.sharepoint.us:/sites/team"

    def test_multiple_trailing_slashes(self):
        result = sharepoint_url_to_graph_path("https://contoso.sharepoint.us/sites/team///")
        assert result == "contoso.sharepoint.us:/sites/team"


class TestURLConverterAdditionalPathSegments:
    """Verify additional path segments after site path are preserved.

    Validates: Requirements 1.3
    """

    def test_subsite_path(self):
        result = sharepoint_url_to_graph_path(
            "https://contoso.sharepoint.us/sites/team/subsite"
        )
        assert result == "contoso.sharepoint.us:/sites/team/subsite"

    def test_deeply_nested_path(self):
        result = sharepoint_url_to_graph_path(
            "https://contoso.sharepoint.us/sites/dept/team/project/docs"
        )
        assert result == "contoso.sharepoint.us:/sites/dept/team/project/docs"

    def test_subsite_with_trailing_slash(self):
        result = sharepoint_url_to_graph_path(
            "https://contoso.sharepoint.us/sites/team/subsite/"
        )
        assert result == "contoso.sharepoint.us:/sites/team/subsite"


class TestURLConverterValueErrors:
    """Verify ValueError is raised for invalid inputs.

    Validates: Requirements 1.4, 1.5
    """

    def test_empty_string(self):
        with pytest.raises(ValueError):
            sharepoint_url_to_graph_path("")

    def test_none_input(self):
        with pytest.raises(ValueError):
            sharepoint_url_to_graph_path(None)

    def test_url_missing_sites_segment(self):
        with pytest.raises(ValueError, match="/sites/"):
            sharepoint_url_to_graph_path("https://contoso.sharepoint.us/teams/project")

    def test_url_with_only_host(self):
        with pytest.raises(ValueError, match="/sites/"):
            sharepoint_url_to_graph_path("https://contoso.sharepoint.us")


# ---------------------------------------------------------------------------
# Task 3.2: Unit tests for session management and auth header
# ---------------------------------------------------------------------------

from unittest.mock import patch, MagicMock

import requests

from sharepoint_graph import GRAPH_BASE_URL, SharePointGraphClient


class TestSessionAuthHeader:
    """Verify session is created with correct Authorization header.

    Validates: Requirements 7.1, 7.2
    """

    def test_session_has_bearer_token_header(self):
        client = SharePointGraphClient(token="my-secret-token")
        assert client._session.headers["Authorization"] == "Bearer my-secret-token"

    def test_session_header_includes_arbitrary_token(self):
        client = SharePointGraphClient(token="abc123xyz")
        assert client._session.headers["Authorization"] == "Bearer abc123xyz"

    def test_session_is_requests_session(self):
        client = SharePointGraphClient(token="tok")
        assert isinstance(client._session, requests.Session)


class TestContextManagerClosesSession:
    """Verify context manager closes the session on exit.

    Validates: Requirement 7.3
    """

    def test_exit_closes_session(self):
        with patch("sharepoint_graph.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session_cls.return_value = mock_session

            with SharePointGraphClient(token="tok") as client:
                pass  # enter and exit

            mock_session.close.assert_called_once()

    def test_context_manager_returns_self(self):
        client = SharePointGraphClient(token="tok")
        with client as ctx:
            assert ctx is client


class TestDefaultBaseUrl:
    """Verify default base_url is the GovCloud Graph endpoint.

    Validates: Requirement 6.1
    """

    def test_default_base_url_is_govcloud(self):
        client = SharePointGraphClient(token="tok")
        assert client.base_url == "https://graph.microsoft.us/v1.0"

    def test_default_base_url_matches_module_constant(self):
        client = SharePointGraphClient(token="tok")
        assert client.base_url == GRAPH_BASE_URL


class TestCustomBaseUrl:
    """Verify custom base_url overrides the default.

    Validates: Requirement 6.2
    """

    def test_custom_base_url_overrides_default(self):
        client = SharePointGraphClient(token="tok", base_url="https://custom.api/v1.0")
        assert client.base_url == "https://custom.api/v1.0"

    def test_none_base_url_falls_back_to_default(self):
        client = SharePointGraphClient(token="tok", base_url=None)
        assert client.base_url == GRAPH_BASE_URL


# ---------------------------------------------------------------------------
# Task 5.4: Unit tests for site resolution
# ---------------------------------------------------------------------------


def _make_client(token="test-token", base_url="https://graph.microsoft.us/v1.0"):
    """Create a SharePointGraphClient with a mocked session for testing."""
    client = SharePointGraphClient(token=token, base_url=base_url)
    client._session = MagicMock()
    return client


def _mock_response(ok=True, status_code=200, json_data=None, text=""):
    """Create a mock requests.Response with the given attributes."""
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = text
    return resp


class TestResolveSiteSuccess:
    """Verify successful site resolution returns the site ID.

    Validates: Requirements 2.1, 2.2
    """

    def test_returns_site_id_from_json_response(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=True,
            status_code=200,
            json_data={"id": "contoso.sharepoint.us,abc-123,def-456"},
        )

        result = client.resolve_site("contoso.sharepoint.us:/sites/team")

        assert result == "contoso.sharepoint.us,abc-123,def-456"

    def test_returns_simple_site_id(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=True,
            status_code=200,
            json_data={"id": "site-id-xyz"},
        )

        result = client.resolve_site("host:/sites/mysite")

        assert result == "site-id-xyz"


class TestResolveSite404:
    """Verify HTTP 404 raises SiteNotFoundError.

    Validates: Requirement 2.3
    """

    def test_raises_site_not_found_error_on_404(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=False,
            status_code=404,
            json_data={"error": {"message": "Site not found"}},
            text="Site not found",
        )

        with pytest.raises(SiteNotFoundError) as exc_info:
            client.resolve_site("host:/sites/nonexistent")

        assert exc_info.value.status_code == 404
        assert "Site not found" in exc_info.value.message

    def test_site_not_found_is_catchable_as_sharepoint_graph_error(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=False,
            status_code=404,
            json_data={"error": {"message": "Not found"}},
            text="Not found",
        )

        with pytest.raises(SharePointGraphError):
            client.resolve_site("host:/sites/missing")


class TestResolveSiteOtherHTTPErrors:
    """Verify other HTTP errors raise SharePointGraphError with status code and message.

    Validates: Requirement 2.4
    """

    def test_raises_sharepoint_graph_error_on_403(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=False,
            status_code=403,
            json_data={"error": {"message": "Access denied"}},
            text="Access denied",
        )

        with pytest.raises(SharePointGraphError) as exc_info:
            client.resolve_site("host:/sites/restricted")

        assert exc_info.value.status_code == 403
        assert "Access denied" in exc_info.value.message

    def test_raises_sharepoint_graph_error_on_500(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=False,
            status_code=500,
            json_data={"error": {"message": "Internal server error"}},
            text="Internal server error",
        )

        with pytest.raises(SharePointGraphError) as exc_info:
            client.resolve_site("host:/sites/broken")

        assert exc_info.value.status_code == 500
        assert "Internal server error" in exc_info.value.message

    def test_falls_back_to_response_text_when_json_missing(self):
        client = _make_client()
        resp = _mock_response(
            ok=False,
            status_code=502,
            text="Bad Gateway",
        )
        resp.json.side_effect = ValueError("No JSON")
        client._session.get.return_value = resp

        with pytest.raises(SharePointGraphError) as exc_info:
            client.resolve_site("host:/sites/down")

        assert exc_info.value.status_code == 502
        assert "Bad Gateway" in exc_info.value.message

    def test_not_a_site_not_found_error_on_non_404(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=False,
            status_code=401,
            json_data={"error": {"message": "Unauthorized"}},
            text="Unauthorized",
        )

        with pytest.raises(SharePointGraphError) as exc_info:
            client.resolve_site("host:/sites/noauth")

        assert not isinstance(exc_info.value, SiteNotFoundError)


class TestResolveSiteAuthHeader:
    """Verify Authorization header is sent with the request.

    Validates: Requirement 7.1
    """

    def test_session_created_with_bearer_token(self):
        client = SharePointGraphClient(token="my-bearer-token")
        assert client._session.headers["Authorization"] == "Bearer my-bearer-token"

    def test_mock_session_get_called_once(self):
        client = _make_client(token="tok123")
        client._session.get.return_value = _mock_response(
            ok=True, json_data={"id": "site-1"}
        )

        client.resolve_site("host:/sites/team")

        client._session.get.assert_called_once()


class TestResolveSiteRequestURL:
    """Verify request URL starts with configured base_url.

    Validates: Requirements 6.3, 2.1
    """

    def test_url_starts_with_default_base_url(self):
        client = _make_client(base_url="https://graph.microsoft.us/v1.0")
        client._session.get.return_value = _mock_response(
            ok=True, json_data={"id": "s1"}
        )

        client.resolve_site("contoso.sharepoint.us:/sites/team")

        call_args = client._session.get.call_args
        url = call_args[0][0]
        assert url.startswith("https://graph.microsoft.us/v1.0")

    def test_url_starts_with_custom_base_url(self):
        client = _make_client(base_url="https://custom.graph.api/v2.0")
        client._session.get.return_value = _mock_response(
            ok=True, json_data={"id": "s2"}
        )

        client.resolve_site("host:/sites/mysite")

        call_args = client._session.get.call_args
        url = call_args[0][0]
        assert url.startswith("https://custom.graph.api/v2.0")

    def test_url_contains_sites_and_graph_site_path(self):
        client = _make_client(base_url="https://graph.microsoft.us/v1.0")
        client._session.get.return_value = _mock_response(
            ok=True, json_data={"id": "s3"}
        )

        client.resolve_site("contoso.sharepoint.us:/sites/team")

        call_args = client._session.get.call_args
        url = call_args[0][0]
        assert url == "https://graph.microsoft.us/v1.0/sites/contoso.sharepoint.us:/sites/team"


# ---------------------------------------------------------------------------
# Task 5.5: Unit tests for drive listing and lookup
# ---------------------------------------------------------------------------


class TestListDrivesSuccess:
    """Verify successful drive listing returns multiple DriveInfo records.

    Validates: Requirements 3.1, 3.2
    """

    def test_returns_list_of_drive_info(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=True,
            status_code=200,
            json_data={
                "value": [
                    {"id": "drive-1", "name": "Documents"},
                    {"id": "drive-2", "name": "Shared Files"},
                    {"id": "drive-3", "name": "Archive"},
                ]
            },
        )

        drives = client.list_drives("site-id-abc")

        assert len(drives) == 3
        assert drives[0] == DriveInfo(drive_id="drive-1", drive_name="Documents")
        assert drives[1] == DriveInfo(drive_id="drive-2", drive_name="Shared Files")
        assert drives[2] == DriveInfo(drive_id="drive-3", drive_name="Archive")

    def test_request_url_targets_site_drives_endpoint(self):
        client = _make_client(base_url="https://graph.microsoft.us/v1.0")
        client._session.get.return_value = _mock_response(
            ok=True,
            status_code=200,
            json_data={"value": [{"id": "d1", "name": "Docs"}]},
        )

        client.list_drives("my-site-id")

        call_url = client._session.get.call_args[0][0]
        assert call_url == "https://graph.microsoft.us/v1.0/sites/my-site-id/drives"


class TestGetDriveByNameSuccess:
    """Verify get_drive_by_name returns the correct drive when found.

    Validates: Requirement 3.3
    """

    def test_returns_matching_drive(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=True,
            status_code=200,
            json_data={
                "value": [
                    {"id": "drive-1", "name": "Documents"},
                    {"id": "drive-2", "name": "Shared Files"},
                ]
            },
        )

        result = client.get_drive_by_name("site-id", "Shared Files")

        assert result == DriveInfo(drive_id="drive-2", drive_name="Shared Files")

    def test_case_sensitive_match(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=True,
            status_code=200,
            json_data={
                "value": [
                    {"id": "drive-1", "name": "documents"},
                    {"id": "drive-2", "name": "Documents"},
                ]
            },
        )

        result = client.get_drive_by_name("site-id", "Documents")

        assert result.drive_id == "drive-2"


class TestGetDriveByNameNotFound:
    """Verify get_drive_by_name raises DriveNotFoundError when name not found.

    Validates: Requirement 3.4
    """

    def test_raises_drive_not_found_error(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=True,
            status_code=200,
            json_data={
                "value": [
                    {"id": "drive-1", "name": "Documents"},
                ]
            },
        )

        with pytest.raises(DriveNotFoundError):
            client.get_drive_by_name("site-id", "Nonexistent Library")

    def test_drive_name_included_in_error_message(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=True,
            status_code=200,
            json_data={"value": []},
        )

        with pytest.raises(DriveNotFoundError) as exc_info:
            client.get_drive_by_name("site-id", "My Missing Drive")

        assert "My Missing Drive" in str(exc_info.value)
        assert exc_info.value.drive_name == "My Missing Drive"


class TestListDrivesHTTPError:
    """Verify HTTP errors on drive listing raise SharePointGraphError.

    Validates: Requirement 3.5
    """

    def test_raises_sharepoint_graph_error_on_500(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=False,
            status_code=500,
            json_data={"error": {"message": "Internal server error"}},
            text="Internal server error",
        )

        with pytest.raises(SharePointGraphError) as exc_info:
            client.list_drives("site-id")

        assert exc_info.value.status_code == 500
        assert "Internal server error" in exc_info.value.message

    def test_raises_sharepoint_graph_error_on_401(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=False,
            status_code=401,
            json_data={"error": {"message": "Unauthorized"}},
            text="Unauthorized",
        )

        with pytest.raises(SharePointGraphError) as exc_info:
            client.list_drives("site-id")

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Task 6.2: Unit tests for file listing
# ---------------------------------------------------------------------------


class TestListFilesSinglePageFilesAndFolders:
    """Verify only files (not folders) are yielded from a single-page response.

    Validates: Requirements 4.3, 4.5
    """

    def test_yields_only_items_with_file_facet(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=True,
            status_code=200,
            json_data={
                "value": [
                    {
                        "name": "report.pdf",
                        "id": "file-1",
                        "webUrl": "https://sp.us/report.pdf",
                        "file": {"mimeType": "application/pdf"},
                        "listItem": {"fields": {}},
                    },
                    {
                        "name": "Subfolder",
                        "id": "folder-1",
                        "webUrl": "https://sp.us/Subfolder",
                        "folder": {"childCount": 3},
                    },
                    {
                        "name": "notes.txt",
                        "id": "file-2",
                        "webUrl": "https://sp.us/notes.txt",
                        "file": {"mimeType": "text/plain"},
                        "listItem": {"fields": {}},
                    },
                ]
            },
        )

        items = list(client.list_files("drive-abc"))

        assert len(items) == 2
        assert items[0].name == "report.pdf"
        assert items[0].item_id == "file-1"
        assert items[1].name == "notes.txt"
        assert items[1].item_id == "file-2"

    def test_skips_folder_entries(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=True,
            status_code=200,
            json_data={
                "value": [
                    {
                        "name": "Archive",
                        "id": "folder-1",
                        "webUrl": "https://sp.us/Archive",
                        "folder": {"childCount": 10},
                    },
                ]
            },
        )

        items = list(client.list_files("drive-abc"))

        assert len(items) == 0


class TestListFilesMultiPagePagination:
    """Verify multi-page responses with @odata.nextLink are fully consumed.

    Validates: Requirements 4.4, 6.4
    """

    def test_follows_next_link_and_yields_all_files(self):
        client = _make_client()

        page1 = _mock_response(
            ok=True,
            status_code=200,
            json_data={
                "value": [
                    {
                        "name": "file1.docx",
                        "id": "f1",
                        "webUrl": "https://sp.us/file1.docx",
                        "file": {},
                        "listItem": {"fields": {}},
                    },
                ],
                "@odata.nextLink": "https://graph.microsoft.us/v1.0/drives/d1/root/children?$skiptoken=abc",
            },
        )
        page2 = _mock_response(
            ok=True,
            status_code=200,
            json_data={
                "value": [
                    {
                        "name": "file2.xlsx",
                        "id": "f2",
                        "webUrl": "https://sp.us/file2.xlsx",
                        "file": {},
                        "listItem": {"fields": {}},
                    },
                    {
                        "name": "file3.pptx",
                        "id": "f3",
                        "webUrl": "https://sp.us/file3.pptx",
                        "file": {},
                        "listItem": {"fields": {}},
                    },
                ],
            },
        )

        client._session.get.side_effect = [page1, page2]

        items = list(client.list_files("d1"))

        assert len(items) == 3
        assert [i.name for i in items] == ["file1.docx", "file2.xlsx", "file3.pptx"]

    def test_three_pages_all_consumed(self):
        client = _make_client()

        page1 = _mock_response(
            ok=True,
            json_data={
                "value": [
                    {"name": "a.txt", "id": "a", "webUrl": "u", "file": {}, "listItem": {"fields": {}}},
                ],
                "@odata.nextLink": "https://graph.microsoft.us/v1.0/next1",
            },
        )
        page2 = _mock_response(
            ok=True,
            json_data={
                "value": [
                    {"name": "b.txt", "id": "b", "webUrl": "u", "file": {}, "listItem": {"fields": {}}},
                ],
                "@odata.nextLink": "https://graph.microsoft.us/v1.0/next2",
            },
        )
        page3 = _mock_response(
            ok=True,
            json_data={
                "value": [
                    {"name": "c.txt", "id": "c", "webUrl": "u", "file": {}, "listItem": {"fields": {}}},
                ],
            },
        )

        client._session.get.side_effect = [page1, page2, page3]

        items = list(client.list_files("d1"))

        assert len(items) == 3
        assert client._session.get.call_count == 3


class TestListFilesMetadataExtraction:
    """Verify metadata is extracted from listItem.fields into FileItem.

    Validates: Requirement 4.3
    """

    def test_metadata_extracted_from_list_item_fields(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=True,
            status_code=200,
            json_data={
                "value": [
                    {
                        "name": "contract.pdf",
                        "id": "item-99",
                        "webUrl": "https://sp.us/contract.pdf",
                        "file": {"mimeType": "application/pdf"},
                        "listItem": {
                            "fields": {
                                "Author": "Alice",
                                "Department": "Legal",
                                "Year": 2024,
                            }
                        },
                    },
                ]
            },
        )

        items = list(client.list_files("drive-x"))

        assert len(items) == 1
        assert items[0].metadata == {"Author": "Alice", "Department": "Legal", "Year": 2024}

    def test_missing_list_item_fields_defaults_to_empty_dict(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=True,
            status_code=200,
            json_data={
                "value": [
                    {
                        "name": "bare.txt",
                        "id": "item-bare",
                        "webUrl": "https://sp.us/bare.txt",
                        "file": {},
                    },
                ]
            },
        )

        items = list(client.list_files("drive-x"))

        assert items[0].metadata == {}


class TestListFilesEmptyFolder:
    """Verify empty folder (empty value array) yields no items.

    Validates: Requirement 4.1
    """

    def test_empty_value_array_yields_nothing(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=True,
            status_code=200,
            json_data={"value": []},
        )

        items = list(client.list_files("drive-empty"))

        assert items == []


class TestListFilesExpandQueryParam:
    """Verify $expand=listItem($expand=fields) query parameter is included.

    Validates: Requirement 4.7
    """

    def test_first_request_includes_expand_param(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=True,
            json_data={"value": []},
        )

        list(client.list_files("drive-1"))

        call_args = client._session.get.call_args
        _, kwargs = call_args
        assert kwargs.get("params") == {"$expand": "listItem($expand=fields)"}


class TestListFilesFolderPathURLConstruction:
    """Verify folder path URL construction for both empty and non-empty paths.

    Validates: Requirements 4.1, 4.2
    """

    def test_empty_folder_path_uses_root_children(self):
        client = _make_client(base_url="https://graph.microsoft.us/v1.0")
        client._session.get.return_value = _mock_response(
            ok=True,
            json_data={"value": []},
        )

        list(client.list_files("drive-abc", folder_path=""))

        call_url = client._session.get.call_args[0][0]
        assert call_url == "https://graph.microsoft.us/v1.0/drives/drive-abc/root/children"

    def test_non_empty_folder_path_uses_root_colon_syntax(self):
        client = _make_client(base_url="https://graph.microsoft.us/v1.0")
        client._session.get.return_value = _mock_response(
            ok=True,
            json_data={"value": []},
        )

        list(client.list_files("drive-abc", folder_path="Documents/Reports"))

        call_url = client._session.get.call_args[0][0]
        assert call_url == "https://graph.microsoft.us/v1.0/drives/drive-abc/root:/Documents/Reports:/children"


class TestListFilesHTTPErrorOnSecondPage:
    """Verify HTTP error on second page raises SharePointGraphError.

    Validates: Requirement 4.6
    """

    def test_error_on_second_page_raises_sharepoint_graph_error(self):
        client = _make_client()

        page1 = _mock_response(
            ok=True,
            json_data={
                "value": [
                    {"name": "ok.txt", "id": "f1", "webUrl": "u", "file": {}, "listItem": {"fields": {}}},
                ],
                "@odata.nextLink": "https://graph.microsoft.us/v1.0/next-page",
            },
        )
        page2 = _mock_response(
            ok=False,
            status_code=503,
            json_data={"error": {"message": "Service Unavailable"}},
            text="Service Unavailable",
        )

        client._session.get.side_effect = [page1, page2]

        with pytest.raises(SharePointGraphError) as exc_info:
            list(client.list_files("drive-1"))

        assert exc_info.value.status_code == 503
        assert "Service Unavailable" in exc_info.value.message


class TestListFilesNextLinkFollowedAsIs:
    """Verify @odata.nextLink URLs are followed as-is (not prefixed with base_url).

    Validates: Requirement 6.4
    """

    def test_next_link_url_used_verbatim(self):
        client = _make_client(base_url="https://graph.microsoft.us/v1.0")

        next_link_url = "https://graph.microsoft.us/v1.0/drives/d1/root/children?$skiptoken=xyz123"

        page1 = _mock_response(
            ok=True,
            json_data={
                "value": [
                    {"name": "a.txt", "id": "a", "webUrl": "u", "file": {}, "listItem": {"fields": {}}},
                ],
                "@odata.nextLink": next_link_url,
            },
        )
        page2 = _mock_response(
            ok=True,
            json_data={"value": []},
        )

        client._session.get.side_effect = [page1, page2]

        list(client.list_files("d1"))

        # Second call should use the nextLink URL as-is
        second_call_url = client._session.get.call_args_list[1][0][0]
        assert second_call_url == next_link_url

    def test_next_link_call_uses_params_none(self):
        client = _make_client()

        page1 = _mock_response(
            ok=True,
            json_data={
                "value": [
                    {"name": "a.txt", "id": "a", "webUrl": "u", "file": {}, "listItem": {"fields": {}}},
                ],
                "@odata.nextLink": "https://graph.microsoft.us/v1.0/next",
            },
        )
        page2 = _mock_response(
            ok=True,
            json_data={"value": []},
        )

        client._session.get.side_effect = [page1, page2]

        list(client.list_files("d1"))

        # First call has $expand params, second call has params=None
        first_call_kwargs = client._session.get.call_args_list[0][1]
        second_call_kwargs = client._session.get.call_args_list[1][1]
        assert first_call_kwargs.get("params") == {"$expand": "listItem($expand=fields)"}
        assert second_call_kwargs.get("params") is None


# ---------------------------------------------------------------------------
# Task 7.2: Unit tests for file download
# ---------------------------------------------------------------------------


class TestDownloadFileSuccess:
    """Verify successful streaming download returns the response and uses stream=True.

    Validates: Requirements 5.1, 5.2
    """

    def test_returns_response_on_success(self):
        client = _make_client()
        mock_resp = _mock_response(ok=True, status_code=200)
        client._session.get.return_value = mock_resp

        result = client.download_file("drive-1", "item-1")

        assert result is mock_resp

    def test_stream_true_is_passed_to_session_get(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(ok=True, status_code=200)

        client.download_file("drive-abc", "item-xyz")

        _, kwargs = client._session.get.call_args
        assert kwargs.get("stream") is True

    def test_request_url_targets_content_endpoint(self):
        client = _make_client(base_url="https://graph.microsoft.us/v1.0")
        client._session.get.return_value = _mock_response(ok=True, status_code=200)

        client.download_file("d1", "i1")

        call_url = client._session.get.call_args[0][0]
        assert call_url == "https://graph.microsoft.us/v1.0/drives/d1/items/i1/content"


class TestDownloadFile404:
    """Verify HTTP 404 raises GraphFileNotFoundError (not SiteNotFoundError).

    Validates: Requirement 5.3
    """

    def test_raises_graph_file_not_found_error_on_404(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=False,
            status_code=404,
            json_data={"error": {"message": "Item not found"}},
            text="Item not found",
        )

        with pytest.raises(GraphFileNotFoundError) as exc_info:
            client.download_file("drive-1", "missing-item")

        assert exc_info.value.status_code == 404
        assert "Item not found" in exc_info.value.message

    def test_404_is_not_site_not_found_error(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=False,
            status_code=404,
            json_data={"error": {"message": "Not found"}},
            text="Not found",
        )

        with pytest.raises(GraphFileNotFoundError) as exc_info:
            client.download_file("drive-1", "item-gone")

        assert not isinstance(exc_info.value, SiteNotFoundError)

    def test_404_is_catchable_as_sharepoint_graph_error(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=False,
            status_code=404,
            json_data={"error": {"message": "File not found"}},
            text="File not found",
        )

        with pytest.raises(SharePointGraphError):
            client.download_file("drive-1", "item-nope")


class TestDownloadFileOtherHTTPErrors:
    """Verify other HTTP errors raise SharePointGraphError.

    Validates: Requirement 5.4
    """

    def test_raises_sharepoint_graph_error_on_403(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=False,
            status_code=403,
            json_data={"error": {"message": "Access denied"}},
            text="Access denied",
        )

        with pytest.raises(SharePointGraphError) as exc_info:
            client.download_file("drive-1", "item-secret")

        assert exc_info.value.status_code == 403
        assert "Access denied" in exc_info.value.message

    def test_raises_sharepoint_graph_error_on_500(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=False,
            status_code=500,
            json_data={"error": {"message": "Internal server error"}},
            text="Internal server error",
        )

        with pytest.raises(SharePointGraphError) as exc_info:
            client.download_file("drive-1", "item-broken")

        assert exc_info.value.status_code == 500

    def test_non_404_error_is_not_graph_file_not_found(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(
            ok=False,
            status_code=401,
            json_data={"error": {"message": "Unauthorized"}},
            text="Unauthorized",
        )

        with pytest.raises(SharePointGraphError) as exc_info:
            client.download_file("drive-1", "item-noauth")

        assert not isinstance(exc_info.value, GraphFileNotFoundError)


class TestDownloadFileAuthHeader:
    """Verify Authorization header is sent with download requests.

    Validates: Requirement 7.1
    """

    def test_session_created_with_bearer_token(self):
        client = SharePointGraphClient(token="download-token-abc")
        assert client._session.headers["Authorization"] == "Bearer download-token-abc"

    def test_get_called_once_for_download(self):
        client = _make_client(token="tok-dl")
        client._session.get.return_value = _mock_response(ok=True, status_code=200)

        client.download_file("drive-1", "item-1")

        client._session.get.assert_called_once()
