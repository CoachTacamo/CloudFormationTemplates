"""Property-based tests for import_documents module.

All tests mock external dependencies — no real AWS or SharePoint calls.
"""

import io
import json
import logging

import pytest
from hypothesis import given, settings, strategies as st

from import_documents import convert_metadata, get_sort_object_key, SORTED_DOCUMENT_PREFIXES


# ---------------------------------------------------------------------------
# Mock Lambda context fixture
# ---------------------------------------------------------------------------


class _MockLambdaContext:
    """Minimal mock of the AWS Lambda context object.

    Provides the attributes that ``@logger.inject_lambda_context`` reads.
    """

    def __init__(self):
        self.function_name = "test-function"
        self.memory_limit_in_mb = 128
        self.aws_request_id = "test-request-id-123"
        self.function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test-function"
        self.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test-function"


@pytest.fixture
def mock_lambda_context():
    """Return a mock Lambda context suitable for ``@logger.inject_lambda_context``."""
    return _MockLambdaContext()


# ---------------------------------------------------------------------------
# Powertools Logger capture helper
# ---------------------------------------------------------------------------


def capture_powertools_logs(handler_func, *args, **kwargs):
    """Run *handler_func* and return ``(result, log_entries)``.

    Temporarily patches the Powertools Logger's underlying handlers so that
    all log output is written to an in-memory ``StringIO`` buffer.  After the
    handler returns (or raises), the buffer is parsed as JSON-lines and
    returned as a list of dicts.

    Usage::

        result, entries = capture_powertools_logs(handler, event, context)
    """
    buffer = io.StringIO()
    from import_documents import logger as powertools_logger

    underlying = powertools_logger._logger
    original_handlers = underlying.handlers[:]
    underlying.handlers = [logging.StreamHandler(buffer)]
    # Preserve the Powertools JSON formatter on the new handler
    if original_handlers and hasattr(original_handlers[0], 'formatter'):
        underlying.handlers[0].setFormatter(original_handlers[0].formatter)
    try:
        result = handler_func(*args, **kwargs)
    finally:
        underlying.handlers = original_handlers

    entries = []
    raw = buffer.getvalue().strip()
    if raw:
        for line in raw.split("\n"):
            if line.strip():
                entries.append(json.loads(line))
    return result, entries


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Values that can appear in SharePoint metadata dicts
_metadata_values = st.one_of(
    st.none(),
    st.integers(),
    st.booleans(),
    st.text(),
    st.floats(allow_nan=False),
)

# Random metadata dicts with text keys and mixed-type values
_metadata_dicts = st.dictionaries(
    keys=st.text(min_size=1, max_size=50),
    values=_metadata_values,
    max_size=20,
)


# ---------------------------------------------------------------------------
# Property 3: Metadata conversion type invariant
# Feature: import-documents-lambda, Property 3: Metadata conversion type
#          invariant
# Validates: Requirements 6.1, 6.2, 6.4
# ---------------------------------------------------------------------------


class TestProperty3MetadataConversionTypeInvariant:
    """Feature: import-documents-lambda, Property 3: Metadata conversion type invariant"""

    @given(metadata=_metadata_dicts)
    @settings(max_examples=100)
    def test_all_output_values_are_str_and_none_becomes_empty(self, metadata):
        """**Validates: Requirements 6.1, 6.2, 6.4**

        For any dict[str, object] with None, int, bool, str, float values,
        convert_metadata() SHALL return a dict[str, str] where every value
        is of type str, every key is preserved, and None input values become
        empty strings "".
        """
        result = convert_metadata(metadata)

        # All output values must be type str
        for key, value in result.items():
            assert isinstance(value, str), (
                f"Expected str for key '{key}', got {type(value).__name__}: {value!r}"
            )

        # Keys must be preserved
        assert set(result.keys()) == set(metadata.keys()), (
            f"Keys mismatch: expected {set(metadata.keys())}, got {set(result.keys())}"
        )

        # None input values must become empty string
        for key, original_value in metadata.items():
            if original_value is None:
                assert result[key] == "", (
                    f"Expected '' for None value at key '{key}', got {result[key]!r}"
                )


# ---------------------------------------------------------------------------
# Strategies for Property 4
# ---------------------------------------------------------------------------

# Non-empty file name strings that don't contain `/` (to avoid ambiguity
# in the structural check — a `/` in the input would add extra separators).
_filenames_without_slash = st.text(
    alphabet=st.characters(blacklist_characters="/"),
    min_size=1,
)


# ---------------------------------------------------------------------------
# Property 4: Object key structural invariant
# Feature: import-documents-lambda, Property 4: Object key structural
#          invariant
# Validates: Requirements 7.1, 7.5
# ---------------------------------------------------------------------------


class TestProperty4ObjectKeyStructuralInvariant:
    """Feature: import-documents-lambda, Property 4: Object key structural invariant"""

    @given(filename=_filenames_without_slash)
    @settings(max_examples=100)
    def test_output_has_exactly_one_slash_with_nonempty_prefix_and_original_filename(
        self, filename
    ):
        """**Validates: Requirements 7.1, 7.5**

        For any non-empty file name string (without `/`),
        get_sort_object_key() SHALL return a string containing exactly
        one `/` separator, with a non-empty prefix before the `/` and
        the original file name after the `/`.
        """
        result = get_sort_object_key(filename)

        # Exactly one `/` in the output
        assert result.count("/") == 1, (
            f"Expected exactly one '/' in '{result}', found {result.count('/')}"
        )

        prefix, _, suffix = result.partition("/")

        # Prefix (before `/`) is non-empty
        assert len(prefix) > 0, (
            f"Expected non-empty prefix before '/', got empty in '{result}'"
        )

        # Filename (after `/`) equals the original input filename
        assert suffix == filename, (
            f"Expected filename '{filename}' after '/', got '{suffix}' in '{result}'"
        )


# ---------------------------------------------------------------------------
# Strategies for Property 5
# ---------------------------------------------------------------------------

# Suffix characters that cannot accidentally form a prefix match
_safe_suffix = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=0,
    max_size=80,
)

# A filename that starts with a known prefix (prefix chosen at random)
_prefixed_filename = st.sampled_from(SORTED_DOCUMENT_PREFIXES).flatmap(
    lambda prefix: _safe_suffix.map(lambda suffix: (prefix, prefix + suffix))
)

# Characters that are safe for building filenames (no `/`)
_safe_chars = st.characters(blacklist_characters="/", blacklist_categories=("Cs",))

# A non-empty filename that does NOT start with any known prefix
_non_prefixed_filename = st.text(
    alphabet=_safe_chars,
    min_size=1,
    max_size=80,
).filter(
    lambda name: not any(name.startswith(p) for p in SORTED_DOCUMENT_PREFIXES)
)


# ---------------------------------------------------------------------------
# Property 5: Object key prefix assignment
# Feature: import-documents-lambda, Property 5: Object key prefix assignment
# Validates: Requirements 7.2, 7.3, 7.4
# ---------------------------------------------------------------------------


class TestProperty5ObjectKeyPrefixAssignment:
    """Feature: import-documents-lambda, Property 5: Object key prefix assignment"""

    @given(data=_prefixed_filename)
    @settings(max_examples=100)
    def test_filename_starting_with_known_prefix_uses_that_prefix(self, data):
        """**Validates: Requirements 7.2, 7.4**

        For any file name that starts with one of the SORTED_DOCUMENT_PREFIXES,
        get_sort_object_key() SHALL return a key whose prefix (before the `/`)
        equals the first matching prefix from the list.
        """
        expected_prefix, filename = data
        result = get_sort_object_key(filename)
        actual_prefix = result.split("/", 1)[0]

        # The first matching prefix in SORTED_DOCUMENT_PREFIXES order
        first_match = next(
            p for p in SORTED_DOCUMENT_PREFIXES if filename.startswith(p)
        )

        assert actual_prefix == first_match, (
            f"For filename '{filename}', expected prefix '{first_match}' "
            f"but got '{actual_prefix}'"
        )

    @given(filename=_non_prefixed_filename)
    @settings(max_examples=100)
    def test_filename_not_starting_with_any_prefix_uses_unknown(self, filename):
        """**Validates: Requirements 7.3**

        For any file name that does NOT start with any of the
        SORTED_DOCUMENT_PREFIXES, get_sort_object_key() SHALL return a key
        whose prefix is "Unknown".
        """
        result = get_sort_object_key(filename)
        actual_prefix = result.split("/", 1)[0]

        assert actual_prefix == "Unknown", (
            f"For filename '{filename}', expected prefix 'Unknown' "
            f"but got '{actual_prefix}'"
        )

    @given(data=_prefixed_filename)
    @settings(max_examples=100)
    def test_first_match_wins_when_prefix_is_substring_of_another(self, data):
        """**Validates: Requirements 7.4**

        Since some prefixes could be substrings of others, verify the first
        matching prefix in SORTED_DOCUMENT_PREFIXES order is used.
        """
        _, filename = data
        result = get_sort_object_key(filename)
        actual_prefix = result.split("/", 1)[0]

        # Walk the list in order — the first prefix that matches the filename
        # must be the one used.
        for prefix in SORTED_DOCUMENT_PREFIXES:
            if filename.startswith(prefix):
                assert actual_prefix == prefix, (
                    f"First-match-wins violated for '{filename}': "
                    f"expected '{prefix}', got '{actual_prefix}'"
                )
                break


# ---------------------------------------------------------------------------
# Unit Tests — Task 1.5
# ---------------------------------------------------------------------------


class TestConvertMetadataUnit:
    """Unit tests for convert_metadata.

    Validates: Requirements 6.1, 6.2
    """

    def test_none_returns_empty_dict(self):
        """convert_metadata(None) returns an empty dict."""
        assert convert_metadata(None) == {}

    def test_empty_dict_returns_empty_dict(self):
        """convert_metadata({}) returns an empty dict."""
        assert convert_metadata({}) == {}

    def test_mixed_value_types_all_become_str(self):
        """Mixed value types (str, int, bool, None) are all converted to str."""
        metadata = {
            "title": "My Document",
            "version": 42,
            "active": True,
            "archived": False,
            "notes": None,
        }
        result = convert_metadata(metadata)

        assert result == {
            "title": "My Document",
            "version": "42",
            "active": "True",
            "archived": "False",
            "notes": "",
        }
        # Every value must be a str instance
        for value in result.values():
            assert isinstance(value, str)

    def test_none_value_becomes_empty_string(self):
        """None values specifically become empty strings, not 'None'."""
        result = convert_metadata({"key": None})
        assert result["key"] == ""

    def test_float_value_converted_to_str(self):
        """Float values are converted via str()."""
        result = convert_metadata({"score": 3.14})
        assert result["score"] == "3.14"

    def test_keys_are_preserved(self):
        """All input keys appear in the output."""
        metadata = {"a": 1, "b": "two", "c": None}
        result = convert_metadata(metadata)
        assert set(result.keys()) == {"a", "b", "c"}


class TestGetSortObjectKeyUnit:
    """Unit tests for get_sort_object_key.

    Validates: Requirements 7.1, 7.2, 7.3, 7.4
    """

    def test_pol_prefix(self):
        assert get_sort_object_key("POL-001 Policy Document.pdf") == "POL/POL-001 Policy Document.pdf"

    def test_pro_prefix(self):
        assert get_sort_object_key("PRO-100 Procedure Guide.docx") == "PRO/PRO-100 Procedure Guide.docx"

    def test_msm_prefix(self):
        assert get_sort_object_key("MSM-050 Management Manual.pdf") == "MSM/MSM-050 Management Manual.pdf"

    def test_wi_prefix(self):
        assert get_sort_object_key("WI-200 Work Instruction.pdf") == "WI/WI-200 Work Instruction.pdf"

    def test_maa_prefix(self):
        assert get_sort_object_key("MAA-010 Maintenance Advisory.pdf") == "MAA/MAA-010 Maintenance Advisory.pdf"

    def test_sps_prefix(self):
        assert get_sort_object_key("SPS-300 Supplier Spec.docx") == "SPS/SPS-300 Supplier Spec.docx"

    def test_ssd_prefix(self):
        assert get_sort_object_key("SSD-400 System Design.pdf") == "SSD/SSD-400 System Design.pdf"

    def test_stm_prefix(self):
        assert get_sort_object_key("STM-500 Standard Method.pdf") == "STM/STM-500 Standard Method.pdf"

    def test_unknown_prefix(self):
        """File not matching any prefix gets 'Unknown' folder."""
        assert get_sort_object_key("misc.docx") == "Unknown/misc.docx"

    def test_unknown_prefix_random_name(self):
        assert get_sort_object_key("README.md") == "Unknown/README.md"

    def test_first_match_wins(self):
        """Prefixes are checked in SORTED_DOCUMENT_PREFIXES order; first match wins."""
        # "POL" comes before all others in the list, so a filename starting
        # with "POL" should always map to "POL", not any later prefix.
        result = get_sort_object_key("POL-SPS-overlap.pdf")
        assert result == "POL/POL-SPS-overlap.pdf"

    def test_output_format_has_one_slash(self):
        """Output always has exactly one '/' separating prefix from filename."""
        result = get_sort_object_key("WI-001 Test.pdf")
        assert result.count("/") == 1

    def test_filename_preserved_after_slash(self):
        """The original filename appears after the '/'."""
        filename = "SSD-999 Complex Name (Rev 2).pdf"
        result = get_sort_object_key(filename)
        assert result.endswith(f"/{filename}")


# ---------------------------------------------------------------------------
# Strategies for Property 1
# ---------------------------------------------------------------------------

# Characters that may appear in category entries (printable + whitespace)
_category_chars = st.characters(
    blacklist_characters=",",  # commas are delimiters, not part of entries
    blacklist_categories=("Cs",),
)

# A single category entry: may include leading/trailing whitespace
_category_entry = st.text(alphabet=_category_chars, min_size=0, max_size=20)

# A list of entries that will be joined with commas to form a CSV string
_category_entry_list = st.lists(_category_entry, min_size=0, max_size=15)


def _parse_categories(csv_string: str) -> set[str]:
    """Replicate the CSV category parsing logic from the handler."""
    return {entry.strip() for entry in csv_string.split(",") if entry.strip()}


# ---------------------------------------------------------------------------
# Property 1: CSV category parsing produces the correct set
# Feature: import-documents-lambda, Property 1: CSV category parsing
#          produces the correct set
# Validates: Requirements 3.1, 3.2, 3.3
# ---------------------------------------------------------------------------


class TestProperty1CSVCategoryParsing:
    """Feature: import-documents-lambda, Property 1: CSV category parsing produces the correct set"""

    @given(entries=_category_entry_list)
    @settings(max_examples=100)
    def test_parsed_set_matches_trimmed_nonempty_entries(self, entries):
        """**Validates: Requirements 3.1, 3.2, 3.3**

        For any list of strings joined by commas, parsing the resulting CSV
        string SHALL produce a set containing exactly the non-empty,
        whitespace-trimmed entries. Empty entries and whitespace-only entries
        SHALL be discarded.
        """
        csv_string = ",".join(entries)
        result = _parse_categories(csv_string)

        # Build the expected set: trim each entry, keep only non-empty
        expected = {e.strip() for e in entries if e.strip()}

        assert result == expected, (
            f"CSV string: {csv_string!r}\n"
            f"Expected: {expected}\n"
            f"Got:      {result}"
        )

    @given(entries=_category_entry_list)
    @settings(max_examples=100)
    def test_leading_trailing_commas_produce_same_result(self, entries):
        """**Validates: Requirements 3.2, 3.3**

        Adding leading or trailing commas to a CSV string SHALL not change
        the parsed set, because the extra empty entries are discarded.
        """
        csv_string = ",".join(entries)
        with_extra_commas = "," + csv_string + ","
        assert _parse_categories(csv_string) == _parse_categories(with_extra_commas)

    @given(entries=_category_entry_list)
    @settings(max_examples=100)
    def test_consecutive_commas_produce_same_result(self, entries):
        """**Validates: Requirements 3.3**

        Replacing single commas with consecutive commas SHALL not change
        the parsed set, because the extra empty entries are discarded.
        """
        csv_string = ",".join(entries)
        doubled = ",,".join(entries)
        assert _parse_categories(csv_string) == _parse_categories(doubled)

    def test_empty_string_returns_empty_set(self):
        """**Validates: Requirements 3.1, 3.3**

        An empty CSV string SHALL produce an empty set.
        """
        assert _parse_categories("") == set()

    def test_whitespace_only_entries_discarded(self):
        """**Validates: Requirements 3.2, 3.3**

        A CSV string containing only whitespace entries SHALL produce
        an empty set.
        """
        assert _parse_categories("  ,  ,   ") == set()

    def test_mixed_valid_and_empty_entries(self):
        """**Validates: Requirements 3.1, 3.2, 3.3**

        A CSV string with a mix of valid, empty, and whitespace-only
        entries SHALL produce a set of only the trimmed non-empty entries.
        """
        result = _parse_categories(" POL , , PRO ,  , MSM ")
        assert result == {"POL", "PRO", "MSM"}


# ---------------------------------------------------------------------------
# Helper for Property 2 — replicates the inline category filter logic
# from handler()
# ---------------------------------------------------------------------------


def _passes_category_filter(metadata: dict, categories: set[str]) -> bool:
    """Return True if a file with *metadata* passes the category filter.

    Replicates the inline logic in ``handler()``:
    - If *categories* is empty, every file passes (no filtering).
    - If *categories* is non-empty and metadata has no ``Category`` key,
      the file is skipped (returns False).
    - Otherwise, the first 3 characters of the ``Category`` value are
      checked for membership in *categories*.
    """
    if not categories:
        return True
    file_category = metadata.get("Category")
    if file_category is None:
        return False
    prefix_3 = str(file_category)[:3]
    return prefix_3 in categories


# ---------------------------------------------------------------------------
# Strategies for Property 2
# ---------------------------------------------------------------------------

# Metadata dicts that *may or may not* contain a "Category" key.
# When present, the value can be any type (str, int, bool, float, None).
_metadata_with_optional_category = st.fixed_dictionaries(
    {},
    optional={
        "Category": st.one_of(
            st.text(min_size=0, max_size=30),
            st.integers(),
            st.booleans(),
            st.floats(allow_nan=False),
            st.none(),
        ),
    },
).flatmap(
    lambda base: _metadata_dicts.map(lambda extra: {**extra, **base})
)

# Non-empty sets of 3-character category prefixes (matching the real usage)
_category_sets = st.frozensets(
    st.text(min_size=3, max_size=3, alphabet=st.characters(blacklist_categories=("Cs",))),
    min_size=1,
    max_size=10,
).map(set)


# ---------------------------------------------------------------------------
# Property 2: Category filter correctness
# Feature: import-documents-lambda, Property 2: Category filter correctness
# Validates: Requirements 5.2, 5.3, 5.5
# ---------------------------------------------------------------------------


class TestProperty2CategoryFilterCorrectness:
    """Feature: import-documents-lambda, Property 2: Category filter correctness"""

    @given(metadata=_metadata_with_optional_category, categories=_category_sets)
    @settings(max_examples=100)
    def test_filter_matches_prefix_membership_rule(self, metadata, categories):
        """**Validates: Requirements 5.2, 5.3, 5.5**

        For any file metadata dict and any non-empty category set, the file
        SHALL pass the category filter if and only if:
        (a) the metadata contains a ``Category`` key, AND
        (b) the first 3 characters of the ``Category`` value are present
            in the category set.
        Files without a ``Category`` key SHALL be skipped when the category
        set is non-empty.
        """
        result = _passes_category_filter(metadata, categories)

        if "Category" not in metadata or metadata["Category"] is None:
            # No Category key (or None value treated as missing by .get())
            # → must be skipped when categories is non-empty
            assert result is False, (
                f"Expected file to be skipped (no Category), but filter returned True.\n"
                f"metadata={metadata!r}, categories={categories!r}"
            )
        else:
            prefix_3 = str(metadata["Category"])[:3]
            expected = prefix_3 in categories
            assert result is expected, (
                f"Category prefix '{prefix_3}' membership mismatch.\n"
                f"Expected {expected}, got {result}.\n"
                f"metadata={metadata!r}, categories={categories!r}"
            )

    @given(metadata=_metadata_dicts)
    @settings(max_examples=100)
    def test_empty_category_set_always_passes(self, metadata):
        """**Validates: Requirements 5.2, 5.3**

        When the category set is empty, every file SHALL pass the filter
        regardless of its metadata.
        """
        assert _passes_category_filter(metadata, set()) is True, (
            f"Expected file to pass with empty category set, but it was filtered.\n"
            f"metadata={metadata!r}"
        )

    @given(categories=_category_sets)
    @settings(max_examples=100)
    def test_missing_category_key_skipped_when_categories_nonempty(self, categories):
        """**Validates: Requirements 5.5**

        When the category set is non-empty and the metadata dict does NOT
        contain a ``Category`` key, the file SHALL be skipped.
        """
        metadata_without_category = {"Title": "Some Doc", "Version": 1}
        assert _passes_category_filter(metadata_without_category, categories) is False, (
            f"Expected file without Category key to be skipped.\n"
            f"categories={categories!r}"
        )


# ---------------------------------------------------------------------------
# Unit Tests — Task 5.1: Environment variable validation
# Validates: Requirements 2.1–2.8
# ---------------------------------------------------------------------------

import os
from unittest.mock import patch, MagicMock

from import_documents import handler

# All 6 required env vars with valid values
_VALID_ENV = {
    "clientId": "test-client-id",
    "clientSecret": "test-client-secret",
    "tenantId": "test-tenant-id",
    "sharepointUrl": "https://contoso.sharepoint.us/sites/team",
    "driveName": "Documents",
    "outputBucket": "my-bucket",
}

_REQUIRED_VARS = [
    "clientId",
    "clientSecret",
    "tenantId",
    "sharepointUrl",
    "driveName",
    "outputBucket",
]


class TestEnvVarValidation:
    """Unit tests for required environment variable validation.

    Validates: Requirements 2.1–2.8
    """

    # --- Missing required variable tests (Req 2.1–2.6) ---

    @pytest.mark.parametrize("missing_var", _REQUIRED_VARS)
    def test_missing_required_var_raises_valueerror(self, missing_var, mock_lambda_context):
        """Each missing required variable raises ValueError naming the variable."""
        env = {k: v for k, v in _VALID_ENV.items() if k != missing_var}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match=missing_var):
                handler({}, mock_lambda_context)

    # --- Empty string required variable tests (Req 2.1–2.6) ---

    @pytest.mark.parametrize("empty_var", _REQUIRED_VARS)
    def test_empty_required_var_raises_valueerror(self, empty_var, mock_lambda_context):
        """Each empty-string required variable raises ValueError naming the variable."""
        env = {**_VALID_ENV, empty_var: ""}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match=empty_var):
                handler({}, mock_lambda_context)

    # --- Optional csvCategories missing → no filtering (Req 2.7) ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_missing_csv_categories_means_no_filtering(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """When csvCategories is absent, all files are imported (no filtering)."""
        # Set up mocks so handler proceeds past validation
        mock_auth.get_access_token.return_value = "fake-token"
        mock_graph.sharepoint_url_to_graph_path.return_value = "contoso.sharepoint.us:/sites/team"

        mock_client = MagicMock()
        mock_graph.SharePointGraphClient.return_value.__enter__ = MagicMock(
            return_value=mock_client
        )
        mock_graph.SharePointGraphClient.return_value.__exit__ = MagicMock(
            return_value=False
        )
        mock_client.resolve_site.return_value = "site-id"

        drive = MagicMock()
        drive.drive_id = "drive-id"
        mock_client.get_drive_by_name.return_value = drive

        # Create a file WITHOUT a Category key — if filtering were active,
        # this file would be skipped.
        file_item = MagicMock()
        file_item.name = "test.pdf"
        file_item.metadata = {"Title": "Test"}  # no Category key
        file_item.web_url = "https://contoso.sharepoint.us/test.pdf"
        file_item.drive_id = "drive-id"
        file_item.item_id = "item-id"
        mock_client.list_files.return_value = iter([file_item])

        mock_response = MagicMock()
        mock_response.content = b"file-bytes"
        mock_client.download_file.return_value = mock_response

        # Env without csvCategories
        env = {**_VALID_ENV}  # no csvCategories key
        with patch.dict(os.environ, env, clear=True):
            result = handler({}, mock_lambda_context)

        assert result == "Import Completed"
        # The file should have been uploaded (not skipped)
        mock_boto3.client.return_value.put_object.assert_called_once()

    # --- Optional sharePointFolderPath missing → empty string (Req 2.8) ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_missing_folder_path_uses_empty_string(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """When sharePointFolderPath is absent, list_files is called with empty string."""
        mock_auth.get_access_token.return_value = "fake-token"
        mock_graph.sharepoint_url_to_graph_path.return_value = "contoso.sharepoint.us:/sites/team"

        mock_client = MagicMock()
        mock_graph.SharePointGraphClient.return_value.__enter__ = MagicMock(
            return_value=mock_client
        )
        mock_graph.SharePointGraphClient.return_value.__exit__ = MagicMock(
            return_value=False
        )
        mock_client.resolve_site.return_value = "site-id"

        drive = MagicMock()
        drive.drive_id = "drive-id"
        mock_client.get_drive_by_name.return_value = drive
        mock_client.list_files.return_value = iter([])  # no files

        # Env without sharePointFolderPath
        env = {**_VALID_ENV}  # no sharePointFolderPath key
        with patch.dict(os.environ, env, clear=True):
            handler({}, mock_lambda_context)

        # list_files should have been called with empty string folder path
        mock_client.list_files.assert_called_once_with("drive-id", "")


# ---------------------------------------------------------------------------
# Unit Tests — Task 5.2: Handler orchestration (end-to-end with mocks)
# Validates: Requirements 4.1–4.5, 8.1–8.6, 9.1–9.3
# ---------------------------------------------------------------------------


class TestHandlerOrchestration:
    """End-to-end handler tests with all external dependencies mocked.

    Validates: Requirements 4.1–4.5, 8.1–8.6, 9.1–9.3
    """

    def _make_file_item(self, name, item_id="item-1", drive_id="drive-id",
                        web_url=None, metadata=None):
        """Create a MagicMock that behaves like a FileItem."""
        f = MagicMock()
        f.name = name
        f.item_id = item_id
        f.drive_id = drive_id
        f.web_url = web_url or f"https://contoso.sharepoint.us/{name}"
        f.metadata = metadata if metadata is not None else {}
        return f

    def _setup_mocks(self, mock_auth, mock_graph, mock_boto3, files=None,
                     folder_path=""):
        """Wire up the standard mock chain for a successful handler run."""
        mock_auth.get_access_token.return_value = "test-token"
        mock_graph.sharepoint_url_to_graph_path.return_value = (
            "contoso.sharepoint.us:/sites/team"
        )

        mock_client = MagicMock()
        mock_graph.SharePointGraphClient.return_value.__enter__ = MagicMock(
            return_value=mock_client
        )
        mock_graph.SharePointGraphClient.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_client.resolve_site.return_value = "site-id-123"

        drive = MagicMock()
        drive.drive_id = "drive-id-456"
        mock_client.get_drive_by_name.return_value = drive

        mock_client.list_files.return_value = iter(files or [])

        mock_download = MagicMock()
        mock_download.content = b"file-content-bytes"
        mock_client.download_file.return_value = mock_download

        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        return mock_client, mock_s3

    # --- Req 4.1: get_access_token called once ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_get_access_token_called_once(self, mock_auth, mock_graph, mock_boto3, mock_lambda_context):
        """get_access_token() is called exactly once."""
        self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            handler({}, mock_lambda_context)
        mock_auth.get_access_token.assert_called_once()

    # --- Req 4.2: sharepoint_url_to_graph_path called with correct URL ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_url_to_graph_path_called_with_sharepoint_url(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """sharepoint_url_to_graph_path() is called with the sharepointUrl env var."""
        self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            handler({}, mock_lambda_context)
        mock_graph.sharepoint_url_to_graph_path.assert_called_once_with(
            _VALID_ENV["sharepointUrl"]
        )

    # --- Req 4.3: SharePointGraphClient created with token ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_graph_client_created_with_token(self, mock_auth, mock_graph, mock_boto3, mock_lambda_context):
        """SharePointGraphClient is instantiated with the bearer token."""
        self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            handler({}, mock_lambda_context)
        mock_graph.SharePointGraphClient.assert_called_once_with("test-token")

    # --- Req 4.4, 4.5: resolve_site, get_drive_by_name, list_files called in order ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_resolve_site_called_with_graph_path(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """resolve_site() is called with the converted graph site path."""
        mock_client, _ = self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            handler({}, mock_lambda_context)
        mock_client.resolve_site.assert_called_once_with(
            "contoso.sharepoint.us:/sites/team"
        )

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_get_drive_by_name_called_with_site_id_and_drive_name(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """get_drive_by_name() is called with site_id and driveName."""
        mock_client, _ = self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            handler({}, mock_lambda_context)
        mock_client.get_drive_by_name.assert_called_once_with(
            "site-id-123", "Documents"
        )

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_list_files_called_with_drive_id_and_folder_path(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """list_files() is called with drive_id and folder path."""
        mock_client, _ = self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            handler({}, mock_lambda_context)
        mock_client.list_files.assert_called_once_with("drive-id-456", "")

    # --- Req 8.1–8.4: put_object called with correct params for each file ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_put_object_called_for_each_file_with_correct_params(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """put_object() is called once per file with correct Bucket, Key, Body, Metadata, Tagging."""
        file1 = self._make_file_item(
            "POL-001 Policy.pdf",
            item_id="item-1",
            drive_id="drive-id-456",
            web_url="https://contoso.sharepoint.us/POL-001 Policy.pdf",
            metadata={"Title": "Policy Doc"},
        )
        file2 = self._make_file_item(
            "misc.docx",
            item_id="item-2",
            drive_id="drive-id-456",
            web_url="https://contoso.sharepoint.us/misc.docx",
            metadata={"Title": "Misc"},
        )

        mock_client, mock_s3 = self._setup_mocks(
            mock_auth, mock_graph, mock_boto3, files=[file1, file2]
        )

        with patch.dict(os.environ, _VALID_ENV, clear=True):
            result = handler({}, mock_lambda_context)

        assert mock_s3.put_object.call_count == 2

        # First file: POL prefix
        call1 = mock_s3.put_object.call_args_list[0]
        assert call1.kwargs["Bucket"] == "my-bucket"
        assert call1.kwargs["Key"] == "POL/POL-001 Policy.pdf"
        assert call1.kwargs["Body"] == b"file-content-bytes"
        assert call1.kwargs["Metadata"]["Title"] == "Policy Doc"
        assert call1.kwargs["Metadata"]["Original Document Url"] == (
            "https://contoso.sharepoint.us/POL-001 Policy.pdf"
        )
        assert call1.kwargs["Tagging"] == "Project=KnowledgeAssistant"

        # Second file: Unknown prefix
        call2 = mock_s3.put_object.call_args_list[1]
        assert call2.kwargs["Bucket"] == "my-bucket"
        assert call2.kwargs["Key"] == "Unknown/misc.docx"
        assert call2.kwargs["Metadata"]["Original Document Url"] == (
            "https://contoso.sharepoint.us/misc.docx"
        )
        assert call2.kwargs["Tagging"] == "Project=KnowledgeAssistant"

    # --- Req 9.2: Return value is "Import Completed" ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_handler_returns_import_completed(self, mock_auth, mock_graph, mock_boto3, mock_lambda_context):
        """handler() returns 'Import Completed' on success."""
        self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            result = handler({}, mock_lambda_context)
        assert result == "Import Completed"

    # --- Req 8.5: With folder path, file path becomes folder/filename ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_folder_path_prepended_to_filename(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """When sharePointFolderPath is set, file path is folder/filename."""
        file1 = self._make_file_item(
            "WI-100 Instruction.pdf",
            item_id="item-1",
            drive_id="drive-id-456",
            web_url="https://contoso.sharepoint.us/WI-100 Instruction.pdf",
        )
        mock_client, mock_s3 = self._setup_mocks(
            mock_auth, mock_graph, mock_boto3, files=[file1]
        )

        env_with_folder = {**_VALID_ENV, "sharePointFolderPath": "subfolder"}
        with patch.dict(os.environ, env_with_folder, clear=True):
            handler({}, mock_lambda_context)

        # list_files should receive the folder path
        mock_client.list_files.assert_called_once_with("drive-id-456", "subfolder")

        # Object key should use folder/filename → get_sort_object_key("subfolder/WI-100 Instruction.pdf")
        # Since "subfolder/WI-100 Instruction.pdf" doesn't start with any prefix, it becomes Unknown/
        call = mock_s3.put_object.call_args_list[0]
        assert call.kwargs["Key"] == "Unknown/subfolder/WI-100 Instruction.pdf"

    # --- Req 8.5 (no folder): Without folder path, file path is just filename ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_no_folder_path_uses_filename_only(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """When sharePointFolderPath is absent, file path is just the filename."""
        file1 = self._make_file_item(
            "POL-050 Safety.pdf",
            item_id="item-1",
            drive_id="drive-id-456",
            web_url="https://contoso.sharepoint.us/POL-050 Safety.pdf",
        )
        mock_client, mock_s3 = self._setup_mocks(
            mock_auth, mock_graph, mock_boto3, files=[file1]
        )

        # No sharePointFolderPath in env
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            handler({}, mock_lambda_context)

        # Object key should use just filename → "POL/POL-050 Safety.pdf"
        call = mock_s3.put_object.call_args_list[0]
        assert call.kwargs["Key"] == "POL/POL-050 Safety.pdf"

    # --- Req 8.6: download_file called for each file ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_download_file_called_for_each_file(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """download_file() is called with correct drive_id and item_id for each file."""
        file1 = self._make_file_item("a.pdf", item_id="id-a", drive_id="drive-id-456")
        file2 = self._make_file_item("b.pdf", item_id="id-b", drive_id="drive-id-456")

        mock_client, _ = self._setup_mocks(
            mock_auth, mock_graph, mock_boto3, files=[file1, file2]
        )

        with patch.dict(os.environ, _VALID_ENV, clear=True):
            handler({}, mock_lambda_context)

        assert mock_client.download_file.call_count == 2
        mock_client.download_file.assert_any_call("drive-id-456", "id-a")
        mock_client.download_file.assert_any_call("drive-id-456", "id-b")

    # --- Req 6.3: Original Document Url added to metadata ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_original_document_url_in_metadata(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """Converted metadata includes 'Original Document Url' from file.web_url."""
        file1 = self._make_file_item(
            "STM-001 Method.pdf",
            web_url="https://contoso.sharepoint.us/sites/team/STM-001 Method.pdf",
            metadata={"Version": 3},
        )
        _, mock_s3 = self._setup_mocks(
            mock_auth, mock_graph, mock_boto3, files=[file1]
        )

        with patch.dict(os.environ, _VALID_ENV, clear=True):
            handler({}, mock_lambda_context)

        call = mock_s3.put_object.call_args_list[0]
        assert call.kwargs["Metadata"]["Original Document Url"] == (
            "https://contoso.sharepoint.us/sites/team/STM-001 Method.pdf"
        )
        # Version should be converted to string
        assert call.kwargs["Metadata"]["Version"] == "3"

    # --- Req 9.1: handler accepts event and context ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_handler_accepts_event_and_context(
        self, mock_auth, mock_graph, mock_boto3
    ):
        """handler() works with any event/context values (they are unused)."""
        self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            result = handler({"key": "value"}, MagicMock())
        assert result == "Import Completed"


# ---------------------------------------------------------------------------
# Unit Tests — Task 5.3: Error propagation
# Validates: Requirements 10.1–10.6
# ---------------------------------------------------------------------------

from sharepoint_auth import AuthenticationError
from sharepoint_graph import SiteNotFoundError, DriveNotFoundError, GraphFileNotFoundError
from botocore.exceptions import ClientError


class TestErrorPropagation:
    """Unit tests for error propagation through the handler.

    Validates: Requirements 10.1–10.6
    """

    def _make_file_item(self, name, item_id="item-1", drive_id="drive-id",
                        web_url=None, metadata=None):
        """Create a MagicMock that behaves like a FileItem."""
        f = MagicMock()
        f.name = name
        f.item_id = item_id
        f.drive_id = drive_id
        f.web_url = web_url or f"https://contoso.sharepoint.us/{name}"
        f.metadata = metadata if metadata is not None else {}
        return f

    def _setup_mocks(self, mock_auth, mock_graph, mock_boto3, files=None):
        """Wire up the standard mock chain for a successful handler run."""
        mock_auth.get_access_token.return_value = "test-token"
        mock_graph.sharepoint_url_to_graph_path.return_value = (
            "contoso.sharepoint.us:/sites/team"
        )

        mock_client = MagicMock()
        mock_graph.SharePointGraphClient.return_value.__enter__ = MagicMock(
            return_value=mock_client
        )
        mock_graph.SharePointGraphClient.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_client.resolve_site.return_value = "site-id-123"

        drive = MagicMock()
        drive.drive_id = "drive-id-456"
        mock_client.get_drive_by_name.return_value = drive

        mock_client.list_files.return_value = iter(files or [])

        mock_download = MagicMock()
        mock_download.content = b"file-content-bytes"
        mock_client.download_file.return_value = mock_download

        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        return mock_client, mock_s3

    # --- Req 10.1: AuthenticationError propagates ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_authentication_error_propagates(self, mock_auth, mock_graph, mock_boto3, mock_lambda_context):
        """AuthenticationError from get_access_token() propagates to caller."""
        # Expose the real exception class so the except clause works with the mock module
        mock_auth.AuthenticationError = AuthenticationError
        mock_auth.get_access_token.side_effect = AuthenticationError(
            "Failed to acquire token"
        )
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            with pytest.raises(AuthenticationError, match="Failed to acquire token"):
                handler({}, mock_lambda_context)

    # --- Req 10.2: ValueError from sharepoint_url_to_graph_path propagates ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_url_conversion_valueerror_propagates(self, mock_auth, mock_graph, mock_boto3, mock_lambda_context):
        """ValueError from sharepoint_url_to_graph_path() propagates to caller."""
        mock_auth.get_access_token.return_value = "test-token"
        mock_graph.sharepoint_url_to_graph_path.side_effect = ValueError(
            "Invalid SharePoint URL"
        )
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            with pytest.raises(ValueError, match="Invalid SharePoint URL"):
                handler({}, mock_lambda_context)

    # --- Req 10.3: SiteNotFoundError propagates ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_site_not_found_error_propagates(self, mock_auth, mock_graph, mock_boto3, mock_lambda_context):
        """SiteNotFoundError from resolve_site() propagates to caller."""
        # Expose the real exception classes so the except clauses work with the mock module
        mock_auth.AuthenticationError = AuthenticationError
        mock_graph.SiteNotFoundError = SiteNotFoundError
        mock_graph.DriveNotFoundError = DriveNotFoundError
        mock_graph.GraphFileNotFoundError = GraphFileNotFoundError
        mock_client, _ = self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        mock_client.resolve_site.side_effect = SiteNotFoundError(
            404, "Site not found"
        )
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            with pytest.raises(SiteNotFoundError):
                handler({}, mock_lambda_context)

    # --- Req 10.4: DriveNotFoundError propagates ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_drive_not_found_error_propagates(self, mock_auth, mock_graph, mock_boto3, mock_lambda_context):
        """DriveNotFoundError from get_drive_by_name() propagates to caller."""
        # Expose the real exception classes so the except clauses work with the mock module
        mock_auth.AuthenticationError = AuthenticationError
        mock_graph.SiteNotFoundError = SiteNotFoundError
        mock_graph.DriveNotFoundError = DriveNotFoundError
        mock_graph.GraphFileNotFoundError = GraphFileNotFoundError
        mock_client, _ = self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        mock_client.get_drive_by_name.side_effect = DriveNotFoundError(
            "Documents"
        )
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            with pytest.raises(DriveNotFoundError, match="Documents"):
                handler({}, mock_lambda_context)

    # --- Req 10.5: GraphFileNotFoundError for one file → other files still processed ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_graph_file_not_found_skips_file_and_continues(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """GraphFileNotFoundError for one file does not prevent other files from uploading."""
        # Ensure the mock module exposes the real exception class so the
        # except clause in handler() can catch it.
        mock_graph.GraphFileNotFoundError = GraphFileNotFoundError

        file1 = self._make_file_item("POL-001 Fail.pdf", item_id="id-fail", drive_id="drive-id-456")
        file2 = self._make_file_item("PRO-002 Success.pdf", item_id="id-ok", drive_id="drive-id-456")

        mock_client, mock_s3 = self._setup_mocks(
            mock_auth, mock_graph, mock_boto3, files=[file1, file2]
        )

        # First download raises GraphFileNotFoundError, second succeeds
        mock_download_ok = MagicMock()
        mock_download_ok.content = b"good-bytes"
        mock_client.download_file.side_effect = [
            GraphFileNotFoundError(404, "File not found"),
            mock_download_ok,
        ]

        with patch.dict(os.environ, _VALID_ENV, clear=True):
            result = handler({}, mock_lambda_context)

        # Handler should still complete successfully
        assert result == "Import Completed"

        # Only the second file should have been uploaded to S3
        mock_s3.put_object.assert_called_once()
        call = mock_s3.put_object.call_args
        assert call.kwargs["Key"] == "PRO/PRO-002 Success.pdf"
        assert call.kwargs["Body"] == b"good-bytes"

    # --- Req 10.6: S3 ClientError propagates ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_s3_client_error_propagates(self, mock_auth, mock_graph, mock_boto3, mock_lambda_context):
        """ClientError from S3 put_object() propagates to caller."""
        # Expose the real exception so the except clause works with the mock module
        mock_graph.GraphFileNotFoundError = GraphFileNotFoundError

        file1 = self._make_file_item("POL-001 Doc.pdf", drive_id="drive-id-456")

        mock_client, mock_s3 = self._setup_mocks(
            mock_auth, mock_graph, mock_boto3, files=[file1]
        )

        mock_s3.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
            "PutObject",
        )

        with patch.dict(os.environ, _VALID_ENV, clear=True):
            with pytest.raises(ClientError):
                handler({}, mock_lambda_context)


# ---------------------------------------------------------------------------
# Unit Tests — Task 5.4: Logging output
# Validates: Requirements 11.1–11.5
# ---------------------------------------------------------------------------


class TestLoggingOutput:
    """Unit tests for handler logging output.

    Validates: Requirements 11.1–11.5
    """

    def _make_file_item(self, name, item_id="item-1", drive_id="drive-id",
                        web_url=None, metadata=None):
        """Create a MagicMock that behaves like a FileItem."""
        f = MagicMock()
        f.name = name
        f.item_id = item_id
        f.drive_id = drive_id
        f.web_url = web_url or f"https://contoso.sharepoint.us/{name}"
        f.metadata = metadata if metadata is not None else {}
        return f

    def _setup_mocks(self, mock_auth, mock_graph, mock_boto3, files=None):
        """Wire up the standard mock chain for a successful handler run."""
        mock_auth.get_access_token.return_value = "test-token"
        mock_graph.sharepoint_url_to_graph_path.return_value = (
            "contoso.sharepoint.us:/sites/team"
        )

        mock_client = MagicMock()
        mock_graph.SharePointGraphClient.return_value.__enter__ = MagicMock(
            return_value=mock_client
        )
        mock_graph.SharePointGraphClient.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_client.resolve_site.return_value = "site-id-123"

        drive = MagicMock()
        drive.drive_id = "drive-id-456"
        mock_client.get_drive_by_name.return_value = drive

        mock_client.list_files.return_value = iter(files or [])

        mock_download = MagicMock()
        mock_download.content = b"file-content-bytes"
        mock_client.download_file.return_value = mock_download

        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        return mock_client, mock_s3

    # --- Req 11.1: "Fetching files" message includes drive name ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_fetching_files_log_includes_drive_name(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """Log message for file listing phase includes the drive name."""
        self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            _, entries = capture_powertools_logs(handler, {}, mock_lambda_context)

        assert any(
            entry.get("drive_name") == "Documents"
            for entry in entries
        ), f"Expected a log entry with drive_name='Documents', got: {entries}"

    # --- Req 11.2: "Moving files to S3" message includes bucket name ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_moving_files_log_includes_bucket_name(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """Log message for S3 upload phase includes the output bucket name."""
        self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            _, entries = capture_powertools_logs(handler, {}, mock_lambda_context)

        assert any(
            entry.get("bucket") == "my-bucket"
            for entry in entries
        ), f"Expected a log entry with bucket='my-bucket', got: {entries}"

    # --- Req 11.3: Category-skipped files are logged ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_category_skipped_file_no_category_logged(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """Files skipped due to missing Category metadata are logged."""
        file_no_cat = self._make_file_item(
            "report.pdf", metadata={"Title": "Report"}
        )
        self._setup_mocks(
            mock_auth, mock_graph, mock_boto3, files=[file_no_cat]
        )

        env = {**_VALID_ENV, "csvCategories": "POL"}
        with patch.dict(os.environ, env, clear=True):
            _, entries = capture_powertools_logs(handler, {}, mock_lambda_context)

        assert any(
            entry.get("file_name") == "report.pdf"
            and entry.get("reason") == "no Category metadata"
            for entry in entries
        ), f"Expected a log entry with file_name='report.pdf' and reason='no Category metadata', got: {entries}"

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_category_skipped_file_prefix_not_in_filter_logged(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """Files skipped due to category prefix not in filter are logged."""
        file_wrong_cat = self._make_file_item(
            "WI-100 Instruction.pdf",
            metadata={"Category": "WI-Work Instructions"},
        )
        self._setup_mocks(
            mock_auth, mock_graph, mock_boto3, files=[file_wrong_cat]
        )

        # Filter only allows POL category, not WI-
        env = {**_VALID_ENV, "csvCategories": "POL"}
        with patch.dict(os.environ, env, clear=True):
            _, entries = capture_powertools_logs(handler, {}, mock_lambda_context)

        assert any(
            entry.get("file_name") == "WI-100 Instruction.pdf"
            and entry.get("category_prefix") == "WI-"
            and entry.get("reason") == "category prefix not in filter"
            for entry in entries
        ), f"Expected a log entry with file_name='WI-100 Instruction.pdf', category_prefix='WI-', and reason='category prefix not in filter', got: {entries}"

    # --- Req 11.4: Failed file downloads logged with file name and error ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_failed_download_logged_with_filename_and_error(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """Failed file downloads are logged with the file name and error details."""
        mock_graph.GraphFileNotFoundError = GraphFileNotFoundError

        file_fail = self._make_file_item(
            "POL-999 Missing.pdf", item_id="id-missing", drive_id="drive-id-456"
        )
        mock_client, _ = self._setup_mocks(
            mock_auth, mock_graph, mock_boto3, files=[file_fail]
        )
        mock_client.download_file.side_effect = GraphFileNotFoundError(
            404, "Item not found"
        )

        with patch.dict(os.environ, _VALID_ENV, clear=True):
            _, entries = capture_powertools_logs(handler, {}, mock_lambda_context)

        assert any(
            entry.get("file_name") == "POL-999 Missing.pdf"
            and entry.get("error_type") == "GraphFileNotFoundError"
            and "error" in entry
            for entry in entries
        ), f"Expected a log entry with file_name='POL-999 Missing.pdf', error_type='GraphFileNotFoundError', and error field, got: {entries}"


# ---------------------------------------------------------------------------
# Unit Tests — Task 6: Structured error logging
# Validates: Requirements 6.1, 6.2, 7.1, 7.2, 8.1, 8.2, 10.1, 10.2, 12.2
# ---------------------------------------------------------------------------


def capture_powertools_logs_allow_raise(handler_func, *args, **kwargs):
    """Run *handler_func* and return log entries, even if the handler raises.

    Like ``capture_powertools_logs`` but does **not** suppress exceptions.
    Returns ``(result_or_none, log_entries, exception_or_none)``.
    """
    buffer = io.StringIO()
    from import_documents import logger as powertools_logger

    underlying = powertools_logger._logger
    original_handlers = underlying.handlers[:]
    underlying.handlers = [logging.StreamHandler(buffer)]
    if original_handlers and hasattr(original_handlers[0], 'formatter'):
        underlying.handlers[0].setFormatter(original_handlers[0].formatter)

    result = None
    exc_caught = None
    try:
        result = handler_func(*args, **kwargs)
    except Exception as exc:
        exc_caught = exc
    finally:
        underlying.handlers = original_handlers

    entries = []
    raw = buffer.getvalue().strip()
    if raw:
        for line in raw.split("\n"):
            if line.strip():
                entries.append(json.loads(line))
    return result, entries, exc_caught


class TestStructuredErrorLogging:
    """Unit tests for structured error log entries.

    Validates: Requirements 6.1, 6.2, 7.1, 7.2, 8.1, 8.2, 10.1, 10.2, 12.2
    """

    # --- Req 6.1, 6.2, 12.2: AuthenticationError structured log ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_authentication_error_structured_log(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """AuthenticationError is logged with error_type and error fields, then re-raised."""
        mock_auth.get_access_token.side_effect = AuthenticationError(
            "token acquisition failed"
        )
        mock_auth.AuthenticationError = AuthenticationError

        with patch.dict(os.environ, _VALID_ENV, clear=True):
            _, entries, exc = capture_powertools_logs_allow_raise(
                handler, {}, mock_lambda_context
            )

        # Verify the exception is still raised to the caller
        assert isinstance(exc, AuthenticationError), (
            f"Expected AuthenticationError to be raised, got: {type(exc)}"
        )

        # Verify structured error log entry
        error_entries = [
            e for e in entries
            if e.get("error_type") == "AuthenticationError"
        ]
        assert len(error_entries) >= 1, (
            f"Expected at least one log entry with error_type='AuthenticationError', "
            f"got: {entries}"
        )
        assert "error" in error_entries[0], (
            f"Expected 'error' field in log entry, got: {error_entries[0]}"
        )

    # --- Req 7.1, 7.2, 12.2: SiteNotFoundError structured log ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_site_not_found_error_structured_log(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """SiteNotFoundError is logged with error_type and error fields, then re-raised."""
        # Auth succeeds
        mock_auth.get_access_token.return_value = "fake-token"
        mock_graph.sharepoint_url_to_graph_path.return_value = (
            "contoso.sharepoint.us:/sites/team"
        )

        # Expose the real exception class on the mock module
        mock_graph.SiteNotFoundError = SiteNotFoundError

        # Set up the context-manager client mock
        mock_client = MagicMock()
        mock_graph.SharePointGraphClient.return_value.__enter__ = MagicMock(
            return_value=mock_client
        )
        mock_graph.SharePointGraphClient.return_value.__exit__ = MagicMock(
            return_value=False
        )

        # resolve_site raises SiteNotFoundError
        mock_client.resolve_site.side_effect = SiteNotFoundError(
            404, "Site not found"
        )

        with patch.dict(os.environ, _VALID_ENV, clear=True):
            _, entries, exc = capture_powertools_logs_allow_raise(
                handler, {}, mock_lambda_context
            )

        # Verify the exception is still raised to the caller
        assert isinstance(exc, SiteNotFoundError), (
            f"Expected SiteNotFoundError to be raised, got: {type(exc)}"
        )

        # Verify structured error log entry
        error_entries = [
            e for e in entries
            if e.get("error_type") == "SiteNotFoundError"
        ]
        assert len(error_entries) >= 1, (
            f"Expected at least one log entry with error_type='SiteNotFoundError', "
            f"got: {entries}"
        )
        assert "error" in error_entries[0], (
            f"Expected 'error' field in log entry, got: {error_entries[0]}"
        )

    # --- Req 8.1, 8.2, 12.2: DriveNotFoundError structured log ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_drive_not_found_error_structured_log(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """DriveNotFoundError is logged with error_type, drive_name, and error fields, then re-raised."""
        # Auth succeeds
        mock_auth.get_access_token.return_value = "fake-token"
        mock_graph.sharepoint_url_to_graph_path.return_value = (
            "contoso.sharepoint.us:/sites/team"
        )

        # Expose the real exception class on the mock module
        mock_graph.DriveNotFoundError = DriveNotFoundError

        # Set up the context-manager client mock
        mock_client = MagicMock()
        mock_graph.SharePointGraphClient.return_value.__enter__ = MagicMock(
            return_value=mock_client
        )
        mock_graph.SharePointGraphClient.return_value.__exit__ = MagicMock(
            return_value=False
        )

        # resolve_site succeeds
        mock_client.resolve_site.return_value = "site-id-123"

        # get_drive_by_name raises DriveNotFoundError
        mock_client.get_drive_by_name.side_effect = DriveNotFoundError(
            "Documents"
        )

        with patch.dict(os.environ, _VALID_ENV, clear=True):
            _, entries, exc = capture_powertools_logs_allow_raise(
                handler, {}, mock_lambda_context
            )

        # Verify the exception is still raised to the caller
        assert isinstance(exc, DriveNotFoundError), (
            f"Expected DriveNotFoundError to be raised, got: {type(exc)}"
        )

        # Verify structured error log entry
        error_entries = [
            e for e in entries
            if e.get("error_type") == "DriveNotFoundError"
        ]
        assert len(error_entries) >= 1, (
            f"Expected at least one log entry with error_type='DriveNotFoundError', "
            f"got: {entries}"
        )
        assert error_entries[0].get("drive_name") == "Documents", (
            f"Expected drive_name='Documents' in log entry, got: {error_entries[0]}"
        )
        assert "error" in error_entries[0], (
            f"Expected 'error' field in log entry, got: {error_entries[0]}"
        )

    # --- Req 10.1, 10.2, 12.2: S3 ClientError structured log ---

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_s3_client_error_structured_log(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """ClientError from s3.put_object() is logged with error_type, bucket, object_key, and error fields, then re-raised."""
        # Auth succeeds
        mock_auth.get_access_token.return_value = "fake-token"
        mock_graph.sharepoint_url_to_graph_path.return_value = (
            "contoso.sharepoint.us:/sites/team"
        )

        # Expose the real exception class on the mock module
        mock_graph.GraphFileNotFoundError = GraphFileNotFoundError

        # Set up the context-manager client mock
        mock_client = MagicMock()
        mock_graph.SharePointGraphClient.return_value.__enter__ = MagicMock(
            return_value=mock_client
        )
        mock_graph.SharePointGraphClient.return_value.__exit__ = MagicMock(
            return_value=False
        )

        # resolve_site and get_drive_by_name succeed
        mock_client.resolve_site.return_value = "site-id-123"

        drive = MagicMock()
        drive.drive_id = "drive-id-456"
        mock_client.get_drive_by_name.return_value = drive

        # list_files returns one file
        file_item = MagicMock()
        file_item.name = "POL-001 Policy.pdf"
        file_item.item_id = "item-1"
        file_item.drive_id = "drive-id-456"
        file_item.web_url = "https://contoso.sharepoint.us/POL-001 Policy.pdf"
        file_item.metadata = {"Title": "Policy Doc"}
        mock_client.list_files.return_value = iter([file_item])

        # download_file succeeds
        mock_download = MagicMock()
        mock_download.content = b"file-content-bytes"
        mock_client.download_file.return_value = mock_download

        # s3.put_object raises ClientError
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3
        mock_s3.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
            "PutObject",
        )

        with patch.dict(os.environ, _VALID_ENV, clear=True):
            _, entries, exc = capture_powertools_logs_allow_raise(
                handler, {}, mock_lambda_context
            )

        # Verify the exception is still raised to the caller
        assert isinstance(exc, ClientError), (
            f"Expected ClientError to be raised, got: {type(exc)}"
        )

        # Verify structured error log entry
        error_entries = [
            e for e in entries
            if e.get("error_type") == "S3ClientError"
        ]
        assert len(error_entries) >= 1, (
            f"Expected at least one log entry with error_type='S3ClientError', "
            f"got: {entries}"
        )
        assert "bucket" in error_entries[0], (
            f"Expected 'bucket' field in log entry, got: {error_entries[0]}"
        )
        assert "object_key" in error_entries[0], (
            f"Expected 'object_key' field in log entry, got: {error_entries[0]}"
        )
        assert "error" in error_entries[0], (
            f"Expected 'error' field in log entry, got: {error_entries[0]}"
        )


# ---------------------------------------------------------------------------
# Unit Tests — Task 7: Lambda context and service name
# Validates: Requirements 1.2, 1.3, 2.1, 2.2, 2.3
# ---------------------------------------------------------------------------


class TestLambdaContextAndServiceName:
    """Unit tests for Lambda context injection and service name in log entries.

    Validates: Requirements 2.1, 2.2, 2.3
    """

    def _setup_mocks(self, mock_auth, mock_graph, mock_boto3, files=None):
        """Wire up the standard mock chain for a successful handler run."""
        mock_auth.get_access_token.return_value = "test-token"
        mock_graph.sharepoint_url_to_graph_path.return_value = (
            "contoso.sharepoint.us:/sites/team"
        )

        mock_client = MagicMock()
        mock_graph.SharePointGraphClient.return_value.__enter__ = MagicMock(
            return_value=mock_client
        )
        mock_graph.SharePointGraphClient.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_client.resolve_site.return_value = "site-id-123"

        drive = MagicMock()
        drive.drive_id = "drive-id-456"
        mock_client.get_drive_by_name.return_value = drive

        mock_client.list_files.return_value = iter(files or [])

        mock_download = MagicMock()
        mock_download.content = b"file-content-bytes"
        mock_client.download_file.return_value = mock_download

        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        return mock_client, mock_s3

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_lambda_context_fields_in_log_entries(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """Log entries contain function_request_id, function_name, and function_memory_size from Lambda context."""
        self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            _, entries = capture_powertools_logs(handler, {}, mock_lambda_context)

        assert len(entries) > 0, "Expected at least one log entry"

        # At least one entry should contain the Lambda context fields
        assert any(
            entry.get("function_request_id") == "test-request-id-123"
            for entry in entries
        ), f"Expected a log entry with function_request_id='test-request-id-123', got: {entries}"

        assert any(
            entry.get("function_name") == "test-function"
            for entry in entries
        ), f"Expected a log entry with function_name='test-function', got: {entries}"

        assert any(
            entry.get("function_memory_size") in (128, "128")
            for entry in entries
        ), f"Expected a log entry with function_memory_size=128, got: {entries}"

    @patch("import_documents.boto3")
    @patch("import_documents.sharepoint_graph")
    @patch("import_documents.sharepoint_auth")
    def test_service_name_in_log_entries(
        self, mock_auth, mock_graph, mock_boto3, mock_lambda_context
    ):
        """All log entries contain service == 'import-documents'.

        Validates: Requirements 1.2, 1.3
        """
        self._setup_mocks(mock_auth, mock_graph, mock_boto3)
        with patch.dict(os.environ, _VALID_ENV, clear=True):
            _, entries = capture_powertools_logs(handler, {}, mock_lambda_context)

        assert len(entries) > 0, "Expected at least one log entry"

        for i, entry in enumerate(entries):
            assert entry.get("service") == "import-documents", (
                f"Log entry {i} has service={entry.get('service')!r}, "
                f"expected 'import-documents'. Full entry: {entry}"
            )


# ---------------------------------------------------------------------------
# Unit Tests — Task 5.5: Module interface
# Validates: Requirements 9.1, 12.1, 12.2, 12.3
# ---------------------------------------------------------------------------

import inspect


class TestModuleInterface:
    """Unit tests for module interface verification.

    Validates: Requirements 9.1, 12.1, 12.2, 12.3
    """

    def test_handler_exists_and_callable_with_event_context_signature(self):
        """handler is callable and has (event, context) signature."""
        assert callable(handler)
        sig = inspect.signature(handler)
        param_names = list(sig.parameters.keys())
        assert param_names == ["event", "context"]

    def test_convert_metadata_is_importable_and_callable(self):
        """convert_metadata is importable and callable independently."""
        assert callable(convert_metadata)

    def test_get_sort_object_key_is_importable_and_callable(self):
        """get_sort_object_key is importable and callable independently."""
        assert callable(get_sort_object_key)

    def test_sorted_document_prefixes_matches_expected_list(self):
        """SORTED_DOCUMENT_PREFIXES equals the expected ordered list."""
        assert SORTED_DOCUMENT_PREFIXES == [
            "POL", "PRO", "MSM", "WI", "MAA", "SPS", "SSD", "STM"
        ]
