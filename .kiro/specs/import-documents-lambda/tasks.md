# Implementation Plan: ImportDocuments Lambda Handler

## Overview

Implement `import_documents.py` — a Python Lambda handler that orchestrates importing documents from a SharePoint document library into an S3 bucket. This is Milestone 3 of the ImportDocuments C#-to-Python conversion, replacing `ImportDocuments.cs`, `MetadataHelper.cs`, and `ObjectKeyHelper.cs`. The module provides a `handler()` function, `convert_metadata()` helper, `get_sort_object_key()` helper, and the `SORTED_DOCUMENT_PREFIXES` constant. All tests mock external dependencies (boto3, sharepoint_auth, sharepoint_graph) — no real AWS or SharePoint calls.

## Tasks

- [x] 1. Create module with constants and helper functions
  - [x] 1.1 Create `import_documents.py` with module docstring, imports (`os`, `logging`, `posixpath`, `boto3`, `sharepoint_auth`, `sharepoint_graph`), and the `SORTED_DOCUMENT_PREFIXES` constant set to `["POL", "PRO", "MSM", "WI", "MAA", "SPS", "SSD", "STM"]`
    - Define `convert_metadata(metadata: dict[str, object] | None) -> dict[str, str]` — returns empty dict for `None`, converts each value via `str()`, converts `None` values to `""`
    - Define `get_sort_object_key(filename: str) -> str` — iterates `SORTED_DOCUMENT_PREFIXES` in order, returns `"{prefix}/{filename}"` for first match, or `"Unknown/{filename}"` if no match
    - _Requirements: 6.1, 6.2, 7.1, 7.2, 7.3, 7.4, 7.5, 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 1.2 Write property test for metadata conversion type invariant
    - **Property 3: Metadata conversion type invariant**
    - Generate random `dict[str, object]` with None, int, bool, str, float values. Verify all output values are `str` and None values become `""`
    - **Validates: Requirements 6.1, 6.2, 6.4**

  - [x] 1.3 Write property test for object key structural invariant
    - **Property 4: Object key structural invariant**
    - Generate random non-empty file name strings. Verify output has exactly one `/` with non-empty prefix and original filename after the `/`
    - **Validates: Requirements 7.1, 7.5**

  - [x] 1.4 Write property test for object key prefix assignment
    - **Property 5: Object key prefix assignment**
    - Generate file names starting with each prefix and file names not starting with any prefix. Verify correct prefix assignment matches first matching prefix or `"Unknown"`
    - **Validates: Requirements 7.2, 7.3, 7.4**

  - [x] 1.5 Write unit tests for `convert_metadata` and `get_sort_object_key`
    - Test `convert_metadata(None)` returns empty dict
    - Test `convert_metadata` with mixed value types (str, int, bool, None) returns all-string dict
    - Test `get_sort_object_key` with each prefix (e.g., `"POL-001 Policy.pdf"` → `"POL/POL-001 Policy.pdf"`)
    - Test `get_sort_object_key` with unknown prefix → `"Unknown/misc.docx"`
    - Test `get_sort_object_key` checks prefixes in order (first match wins)
    - _Requirements: 6.1, 6.2, 7.1, 7.2, 7.3, 7.4_

- [x] 2. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Implement the Lambda handler
  - [x] 3.1 Implement `handler(event, context) -> str` in `import_documents.py`
    - Read all 8 environment variables (`clientId`, `clientSecret`, `tenantId`, `sharepointUrl`, `driveName`, `outputBucket`, `csvCategories`, `sharePointFolderPath`)
    - Validate 6 required variables — raise `ValueError` with variable name if missing/empty
    - Parse `csvCategories` into a `set[str]` (split on comma, trim, discard empties)
    - Default `sharePointFolderPath` to `""`
    - Call `sharepoint_auth.get_access_token()` for bearer token
    - Convert `sharepointUrl` via `sharepoint_url_to_graph_path()`
    - Create `SharePointGraphClient(token)` as context manager
    - Call `resolve_site()`, `get_drive_by_name()`, `list_files()`
    - Log "Fetching files from SharePoint..." and "Moving files to S3 bucket {outputBucket}"
    - For each file: apply category filter, build file path with `posixpath.join()` if folder path set, convert metadata + add `Original Document Url`, generate object key, download file, upload to S3 with `put_object(Bucket, Key, Body, Metadata, Tagging)`
    - Catch `GraphFileNotFoundError` per-file: log and continue
    - Return `"Import Completed"`
    - _Requirements: 1.1–1.8, 2.1–2.8, 3.1–3.4, 4.1–4.5, 5.1–5.5, 6.3, 7.1, 8.1–8.6, 9.1–9.3, 10.1–10.6, 11.1–11.5_

  - [x] 3.2 Write property test for CSV category parsing
    - **Property 1: CSV category parsing produces the correct set**
    - Generate random CSV strings with varying whitespace, commas, empty entries. Verify parsed set matches expected trimmed non-empty entries
    - **Validates: Requirements 3.1, 3.2, 3.3**

  - [x] 3.3 Write property test for category filter correctness
    - **Property 2: Category filter correctness**
    - Generate random FileItem metadata dicts and category sets. Verify filter pass/fail matches the 3-char prefix membership rule. Files without `Category` key are skipped when category set is non-empty
    - **Validates: Requirements 5.2, 5.3, 5.5**

- [x] 4. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Write unit tests for environment variable validation and handler orchestration
  - [x] 5.1 Write unit tests for required environment variable validation
    - Test each of the 6 required variables missing → `ValueError` with correct variable name in message
    - Test each of the 6 required variables empty string → `ValueError` with correct variable name in message
    - Test optional `csvCategories` missing → empty category set (no filtering)
    - Test optional `sharePointFolderPath` missing → empty string folder path
    - _Requirements: 2.1–2.8_

  - [x] 5.2 Write unit tests for handler orchestration (end-to-end with mocks)
    - Mock all external dependencies (`sharepoint_auth`, `sharepoint_graph`, `boto3`)
    - Verify `get_access_token()` called once
    - Verify `sharepoint_url_to_graph_path()` called with correct URL
    - Verify `SharePointGraphClient` created with token
    - Verify `resolve_site()`, `get_drive_by_name()`, `list_files()` called in correct order
    - Verify `put_object()` called for each file with correct Key, Body, Metadata, Tagging (`Project=KnowledgeAssistant`)
    - Verify return value is `"Import Completed"`
    - Test with folder path set → file path is `folder/filename`
    - Test without folder path → file path is just `filename`
    - _Requirements: 4.1–4.5, 8.1–8.6, 9.1–9.3_

  - [x] 5.3 Write unit tests for error propagation
    - Mock `get_access_token()` raising `AuthenticationError` → verify propagation
    - Mock `sharepoint_url_to_graph_path()` raising `ValueError` → verify propagation
    - Mock `resolve_site()` raising `SiteNotFoundError` → verify propagation
    - Mock `get_drive_by_name()` raising `DriveNotFoundError` → verify propagation
    - Mock `download_file()` raising `GraphFileNotFoundError` for one file → verify other files still processed
    - Mock `put_object()` raising `ClientError` → verify propagation
    - _Requirements: 10.1–10.6_

  - [x] 5.4 Write unit tests for logging output
    - Capture log output, verify "Fetching files" message includes drive name
    - Verify "Moving files to S3" message includes bucket name
    - Verify category-skipped files are logged
    - Verify failed file downloads are logged with file name and error details
    - _Requirements: 11.1–11.5_

  - [x] 5.5 Write unit tests for module interface
    - Verify `handler` function exists with `(event, context)` signature
    - Verify `convert_metadata` and `get_sort_object_key` are importable and callable independently
    - Verify `SORTED_DOCUMENT_PREFIXES` matches expected list
    - _Requirements: 9.1, 12.1, 12.2, 12.3_

- [x] 6. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- All tests use `unittest.mock` to mock `boto3`, `sharepoint_auth`, and `sharepoint_graph` — no real AWS or SharePoint calls
- Follow the same test file conventions as `tests/test_sharepoint_auth.py` (Hypothesis + pytest)
- The module lives at the project root as `import_documents.py`, matching `sharepoint_auth.py` and `sharepoint_graph.py`
- Tests go in `tests/test_import_documents.py`
- Property tests validate correctness invariants from the design document; unit tests cover specific behavioral requirements
