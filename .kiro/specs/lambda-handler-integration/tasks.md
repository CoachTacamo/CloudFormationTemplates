# Implementation Plan: Lambda Handler Integration (Powertools Logger)

## Overview

Replace Python's standard `logging` module with `aws_lambda_powertools.Logger` in `import_documents.py`, add structured error handling with log-then-raise pattern, and update the test suite to capture Powertools JSON output instead of `caplog`. All existing functional behavior and tests remain unchanged.

## Tasks

- [x] 1. Install dependency and update imports in `import_documents.py`
  - Install `aws-lambda-powertools`: `python3 -m pip install aws-lambda-powertools`
  - Replace `import logging` with `from aws_lambda_powertools import Logger`
  - Add `from botocore.exceptions import ClientError` import
  - Replace `logger = logging.getLogger(__name__)` with `logger = Logger(service="import-documents")`
  - Verify the module still imports without errors
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Add Lambda context decorator and update info log calls
  - [x] 2.1 Add `@logger.inject_lambda_context` decorator to `handler()`
    - Place decorator directly above the `def handler(event, context)` line
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 2.2 Replace all `logger.info()` calls with structured keyword arguments
    - `logger.info("Fetching files from SharePoint", drive_name=drive_name)` — file listing phase
    - `logger.info("Moving files to S3", bucket=output_bucket)` — S3 upload phase
    - `logger.info("Skipping file", file_name=file.name, reason="no Category metadata")` — no category skip
    - `logger.info("Skipping file", file_name=file.name, category_prefix=prefix_3, reason="category prefix not in filter")` — prefix mismatch skip
    - _Requirements: 3.1, 3.2, 4.1, 4.2, 5.1, 5.2_

- [x] 3. Add structured error handling try/except blocks
  - [x] 3.1 Wrap `sharepoint_auth.get_access_token()` in try/except for `AuthenticationError`
    - Log: `logger.error("Authentication failed", error_type="AuthenticationError", error=str(exc))`
    - Re-raise the exception after logging
    - _Requirements: 6.1, 6.2_

  - [x] 3.2 Wrap `client.resolve_site()` in try/except for `SiteNotFoundError`
    - Log: `logger.error("Site resolution failed", error_type="SiteNotFoundError", error=str(exc))`
    - Re-raise the exception after logging
    - _Requirements: 7.1, 7.2_

  - [x] 3.3 Wrap `client.get_drive_by_name()` in try/except for `DriveNotFoundError`
    - Log: `logger.error("Drive lookup failed", error_type="DriveNotFoundError", drive_name=drive_name, error=str(exc))`
    - Re-raise the exception after logging
    - _Requirements: 8.1, 8.2_

  - [x] 3.4 Update the existing `GraphFileNotFoundError` catch to use structured error logging
    - Log: `logger.error("Failed to download file", file_name=file.name, error_type="GraphFileNotFoundError", error=str(exc))`
    - Continue processing remaining files (existing behavior preserved)
    - _Requirements: 9.1, 9.2_

  - [x] 3.5 Add nested try/except for `ClientError` around `s3.put_object()`
    - Log: `logger.error("S3 upload failed", error_type="S3ClientError", bucket=output_bucket, object_key=object_key, error=str(exc))`
    - Re-raise the exception after logging
    - Nest inside the existing try block so `GraphFileNotFoundError` still catches download failures
    - _Requirements: 10.1, 10.2_

- [x] 4. Checkpoint — Verify `import_documents.py` changes
  - Ensure the module imports cleanly and the handler structure is correct
  - Ensure `convert_metadata()` and `get_sort_object_key()` are NOT modified
  - Ensure all existing tests that don't depend on log capture still pass: `python3 -m pytest tests/test_import_documents.py -v -k "not TestLoggingOutput"`
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [x] 5. Update `TestLoggingOutput` in `tests/test_import_documents.py`
  - [x] 5.1 Add a log capture helper for Powertools Logger
    - Create a helper function or fixture that patches the Powertools Logger's handler to write to a `StringIO` buffer
    - Parse captured output as JSON lines and return list of log entry dicts
    - Remove `import logging` if no longer needed by any test class (check first)
    - _Requirements: 12.1_

  - [x] 5.2 Update `test_fetching_files_log_includes_drive_name`
    - Replace `caplog` usage with the Powertools log capture helper
    - Assert the JSON log entry contains `drive_name` field with value `"Documents"`
    - _Requirements: 3.1, 3.2, 12.3_

  - [x] 5.3 Update `test_moving_files_log_includes_bucket_name`
    - Replace `caplog` usage with the Powertools log capture helper
    - Assert the JSON log entry contains `bucket` field with value `"my-bucket"`
    - _Requirements: 4.1, 4.2, 12.3_

  - [x] 5.4 Update `test_category_skipped_file_no_category_logged`
    - Replace `caplog` usage with the Powertools log capture helper
    - Assert the JSON log entry contains `file_name` and `reason="no Category metadata"`
    - _Requirements: 5.1, 12.3_

  - [x] 5.5 Update `test_category_skipped_file_prefix_not_in_filter_logged`
    - Replace `caplog` usage with the Powertools log capture helper
    - Assert the JSON log entry contains `file_name`, `category_prefix`, and `reason="category prefix not in filter"`
    - _Requirements: 5.2, 12.3_

  - [x] 5.6 Update `test_failed_download_logged_with_filename_and_error`
    - Replace `caplog` usage with the Powertools log capture helper
    - Assert the JSON log entry contains `file_name`, `error_type="GraphFileNotFoundError"`, and `error`
    - _Requirements: 9.1, 12.2_

- [x] 6. Add new structured error logging tests
  - [x] 6.1 Add `test_authentication_error_structured_log`
    - Mock `sharepoint_auth.get_access_token()` to raise `AuthenticationError`
    - Capture log output and verify JSON entry has `error_type="AuthenticationError"` and `error` field
    - Verify the exception is still raised to the caller
    - _Requirements: 6.1, 6.2, 12.2_

  - [x] 6.2 Add `test_site_not_found_error_structured_log`
    - Mock `client.resolve_site()` to raise `SiteNotFoundError`
    - Capture log output and verify JSON entry has `error_type="SiteNotFoundError"` and `error` field
    - Verify the exception is still raised to the caller
    - _Requirements: 7.1, 7.2, 12.2_

  - [x] 6.3 Add `test_drive_not_found_error_structured_log`
    - Mock `client.get_drive_by_name()` to raise `DriveNotFoundError`
    - Capture log output and verify JSON entry has `error_type="DriveNotFoundError"`, `drive_name`, and `error` field
    - Verify the exception is still raised to the caller
    - _Requirements: 8.1, 8.2, 12.2_

  - [x] 6.4 Add `test_s3_client_error_structured_log`
    - Mock `s3.put_object()` to raise `ClientError`
    - Capture log output and verify JSON entry has `error_type="S3ClientError"`, `bucket`, `object_key`, and `error` field
    - Verify the exception is still raised to the caller
    - _Requirements: 10.1, 10.2, 12.2_

- [x] 7. Add Lambda context and service name tests
  - [x] 7.1 Add `test_lambda_context_fields_in_log_entries`
    - Invoke handler with a mock Lambda context object (with `aws_request_id`, `function_name`, `memory_limit_in_mb`)
    - Capture log output and verify JSON entries contain `function_request_id`, `function_name`, `function_memory_size`
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 7.2 Add `test_service_name_in_log_entries`
    - Invoke handler and capture log output
    - Verify all JSON log entries contain `service` field with value `"import-documents"`
    - _Requirements: 1.2, 1.3_

- [x] 8. Final checkpoint — Full test suite passes
  - Run `python3 -m pytest tests/test_import_documents.py -v` and ensure ALL tests pass
  - Verify all existing property-based tests (Properties 1–5) pass without modification
  - Verify all existing unit tests (`TestConvertMetadataUnit`, `TestGetSortObjectKeyUnit`, `TestEnvVarValidation`, `TestHandlerOrchestration`, `TestErrorPropagation`, `TestModuleInterface`) pass without modification
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 12.4_

## Notes

- Only two files are modified: `import_documents.py` and `tests/test_import_documents.py`
- `convert_metadata()` and `get_sort_object_key()` must NOT be touched
- The handler must still raise the same exceptions — structured logging is added BEFORE re-raising
- Powertools Logger writes JSON to stdout; tests must capture stdout/buffer instead of using `caplog`
- All existing property-based and unit tests must pass without modification
