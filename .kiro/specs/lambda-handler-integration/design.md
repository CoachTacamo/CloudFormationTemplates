# Design Document: Lambda Handler Integration (Powertools Logger)

## Overview

This design covers Milestone 4 of the ImportDocuments C#-to-Python conversion: replacing Python's standard `logging` module with `aws_lambda_powertools.Logger` in `import_documents.py`. The handler already works — this milestone upgrades only the logging infrastructure to produce structured JSON logs with Lambda context correlation, structured fields for filtering, and categorized error entries.

No functional behavior changes. The handler continues to validate env vars, authenticate with SharePoint, list/filter files, upload to S3, and propagate the same exceptions. Only the log output format and error observability are upgraded.

### Key Design Decisions

1. **In-place replacement**: The module-level `logger` variable is replaced from `logging.getLogger(__name__)` to `Logger(service="import-documents")`. All call sites update from positional `%s` formatting to keyword arguments.
2. **Decorator-based context injection**: `@logger.inject_lambda_context` on `handler()` automatically adds request ID, function name, version, and memory to every log entry — no manual plumbing.
3. **Log-then-raise pattern for errors**: New try/except blocks catch specific exceptions, log structured error entries with `error_type` and contextual fields, then re-raise. This preserves existing exception propagation behavior.
4. **Test capture via stdout**: Powertools Logger writes JSON to stdout. Tests switch from `caplog` to capturing stdout (via `capsys` or patching the logger's handler) and parsing JSON entries.

## Architecture

The architecture remains unchanged. The only modification is the logging layer within `import_documents.py`:

```mermaid
graph TD
    A[handler entry] -->|@logger.inject_lambda_context| B[Lambda context injected into all logs]
    B --> C[Env var validation]
    C --> D[SharePoint auth]
    D --> E[Graph client operations]
    E --> F[File iteration + S3 upload]
    
    D -->|AuthenticationError| G[Structured error log + re-raise]
    E -->|SiteNotFoundError| G
    E -->|DriveNotFoundError| G
    F -->|GraphFileNotFoundError| H[Structured error log + continue]
    F -->|ClientError| I[Structured error log + re-raise]
    
    style B fill:#e1f5fe
    style G fill:#ffebee
    style H fill:#fff3e0
    style I fill:#ffebee
```

### What Changes

| Component | Before | After |
|---|---|---|
| Import | `import logging` | `from aws_lambda_powertools import Logger` |
| Logger init | `logging.getLogger(__name__)` | `Logger(service="import-documents")` |
| Handler decorator | None | `@logger.inject_lambda_context` |
| Info logs | `logger.info("msg %s", arg)` | `logger.info("msg", field=value)` |
| Error handling | Only `GraphFileNotFoundError` caught | All 5 exception types caught, logged, then re-raised/continued |

### What Does NOT Change

- `convert_metadata()` — unchanged
- `get_sort_object_key()` — unchanged
- `SORTED_DOCUMENT_PREFIXES` — unchanged
- Handler signature `handler(event, context)` — unchanged
- Return value `"Import Completed"` — unchanged
- Exception propagation behavior — unchanged (same exceptions reach the caller)

## Components and Interfaces

### Modified: `import_documents.py`

#### Module-Level Logger

```python
from aws_lambda_powertools import Logger

logger = Logger(service="import-documents")
```

The `service` parameter defaults to `"import-documents"` but is overridable via the `POWERTOOLS_SERVICE_NAME` environment variable (built-in Powertools behavior).

#### Handler Decorator

```python
@logger.inject_lambda_context
def handler(event, context) -> str:
    ...
```

This decorator automatically adds to every log entry during the invocation:
- `function_name`
- `function_memory_size`
- `function_arn`
- `function_request_id` (correlation ID)
- `cold_start`

#### Structured Info Logs

| Operation | Log Call | Structured Fields |
|---|---|---|
| File listing | `logger.info("Fetching files from SharePoint", drive_name=drive_name)` | `drive_name` |
| S3 upload | `logger.info("Moving files to S3", bucket=output_bucket)` | `bucket` |
| Skip (no category) | `logger.info("Skipping file", file_name=file.name, reason="no Category metadata")` | `file_name`, `reason` |
| Skip (prefix mismatch) | `logger.info("Skipping file", file_name=file.name, category_prefix=prefix_3, reason="category prefix not in filter")` | `file_name`, `category_prefix`, `reason` |

#### Structured Error Logs

Each error type gets a try/except block that logs before re-raising (or continuing for `GraphFileNotFoundError`):

| Exception | `error_type` Field | Additional Fields | After Logging |
|---|---|---|---|
| `AuthenticationError` | `"AuthenticationError"` | `error` (message) | Re-raise |
| `SiteNotFoundError` | `"SiteNotFoundError"` | `error` (message) | Re-raise |
| `DriveNotFoundError` | `"DriveNotFoundError"` | `drive_name`, `error` (message) | Re-raise |
| `GraphFileNotFoundError` | `"GraphFileNotFoundError"` | `file_name`, `error` (message) | Continue |
| `ClientError` | `"S3ClientError"` | `bucket`, `object_key`, `error` (message) | Re-raise |

#### Handler Structure (Pseudocode)

```python
@logger.inject_lambda_context
def handler(event, context) -> str:
    # 1. Read + validate env vars (unchanged)
    # 2. Parse csvCategories (unchanged)
    
    # 3. Authenticate — NEW try/except
    try:
        token = sharepoint_auth.get_access_token()
    except sharepoint_auth.AuthenticationError as exc:
        logger.error("Authentication failed", error_type="AuthenticationError", error=str(exc))
        raise

    # 4. Convert URL (unchanged — ValueError propagates naturally)
    graph_site_path = sharepoint_graph.sharepoint_url_to_graph_path(sharepoint_url)

    s3 = boto3.client("s3")

    with sharepoint_graph.SharePointGraphClient(token) as client:
        # 5. Resolve site — NEW try/except
        try:
            site_id = client.resolve_site(graph_site_path)
        except sharepoint_graph.SiteNotFoundError as exc:
            logger.error("Site resolution failed", error_type="SiteNotFoundError", error=str(exc))
            raise

        # 6. Get drive — NEW try/except
        try:
            drive = client.get_drive_by_name(site_id, drive_name)
        except sharepoint_graph.DriveNotFoundError as exc:
            logger.error("Drive lookup failed", error_type="DriveNotFoundError", drive_name=drive_name, error=str(exc))
            raise

        # 7. List files — structured log
        logger.info("Fetching files from SharePoint", drive_name=drive_name)
        files = client.list_files(drive.drive_id, folder_path)

        # 8. Upload loop — structured log
        logger.info("Moving files to S3", bucket=output_bucket)

        for file in files:
            # Category filter (unchanged logic, structured skip logs)
            if categories:
                file_category = file.metadata.get("Category")
                if file_category is None:
                    logger.info("Skipping file", file_name=file.name, reason="no Category metadata")
                    continue
                prefix_3 = str(file_category)[:3]
                if prefix_3 not in categories:
                    logger.info("Skipping file", file_name=file.name, category_prefix=prefix_3, reason="category prefix not in filter")
                    continue

            # Build path, convert metadata, generate key (unchanged)
            ...

            # Download + upload — UPDATED try/except
            try:
                response = client.download_file(file.drive_id, file.item_id)
                s3.put_object(
                    Bucket=output_bucket, Key=object_key,
                    Body=response.content, Metadata=metadata,
                    Tagging="Project=KnowledgeAssistant",
                )
            except sharepoint_graph.GraphFileNotFoundError as exc:
                logger.error("Failed to download file", file_name=file.name, error_type="GraphFileNotFoundError", error=str(exc))
                continue
            except ClientError as exc:
                logger.error("S3 upload failed", error_type="S3ClientError", bucket=output_bucket, object_key=object_key, error=str(exc))
                raise

    return "Import Completed"
```

### Modified: `tests/test_import_documents.py`

#### Test Capture Strategy

Powertools Logger writes JSON to stdout via a `StreamHandler`. Two approaches for capturing in tests:

**Approach A (recommended): Patch the logger's handlers to write to a `StringIO` buffer.**

```python
import io
import json

def capture_powertools_logs(handler_func, *args, **kwargs):
    """Run handler_func and return parsed JSON log entries."""
    buffer = io.StringIO()
    # Temporarily replace the logger's stream handler
    from import_documents import logger as powertools_logger
    original_handlers = powertools_logger.handlers[:]
    powertools_logger.handlers = [logging.StreamHandler(buffer)]
    try:
        result = handler_func(*args, **kwargs)
    finally:
        powertools_logger.handlers = original_handlers
    
    entries = []
    for line in buffer.getvalue().strip().split("\n"):
        if line:
            entries.append(json.loads(line))
    return result, entries
```

**Approach B: Use `capsys` to capture stdout.**

Simpler but may capture non-log stdout. Powertools Logger outputs one JSON object per line, so parsing is straightforward.

#### Test Classes to Update

| Test Class | Change |
|---|---|
| `TestLoggingOutput` | Replace `caplog` with stdout/buffer capture. Assert on parsed JSON fields instead of `caplog.messages`. |
| `TestErrorPropagation` | No changes needed — exceptions still propagate. Optionally add assertions on structured error log fields. |

#### New Test Coverage

New tests (or updated existing tests) should verify:
- Info log entries contain expected structured fields (`drive_name`, `bucket`, `file_name`, `reason`, `category_prefix`)
- Error log entries contain `error_type` and `error` fields
- Lambda context fields (`function_request_id`, `function_name`, etc.) appear in log entries when a mock context is provided
- The `service` field is `"import-documents"` in all log entries

#### Unchanged Tests

All of these must pass without modification:
- `TestProperty1CSVCategoryParsing` (Property 1)
- `TestProperty2CategoryFilterCorrectness` (Property 2)
- `TestProperty3MetadataConversionTypeInvariant` (Property 3)
- `TestProperty4ObjectKeyStructuralInvariant` (Property 4)
- `TestProperty5ObjectKeyPrefixAssignment` (Property 5)
- `TestConvertMetadataUnit`
- `TestGetSortObjectKeyUnit`
- `TestEnvVarValidation`
- `TestHandlerOrchestration`
- `TestErrorPropagation`
- `TestModuleInterface`

## Data Models

No new data models. The only data format change is the log output — from plain text to structured JSON:

### Log Entry Schema (Powertools Logger Output)

```json
{
  "level": "INFO",
  "location": "handler:123",
  "message": "Fetching files from SharePoint",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "service": "import-documents",
  "cold_start": true,
  "function_name": "ImportDocuments",
  "function_memory_size": 512,
  "function_arn": "arn:aws-us-gov:lambda:us-gov-west-1:123456789:function:ImportDocuments",
  "function_request_id": "abc-123-def",
  "xray_trace_id": "1-abc-def",
  "drive_name": "Documents"
}
```

### Error Log Entry Schema

```json
{
  "level": "ERROR",
  "message": "S3 upload failed",
  "service": "import-documents",
  "function_request_id": "abc-123-def",
  "error_type": "S3ClientError",
  "bucket": "my-output-bucket",
  "object_key": "POL/POL-001 Policy.pdf",
  "error": "An error occurred (AccessDenied) when calling the PutObject operation: Access Denied"
}
```

## Error Handling

The error handling strategy adds structured logging to the existing exception propagation pattern. No new exception types are introduced.

### Error Flow

| Exception | Source | Handler Behavior | Log Level | Propagated? |
|---|---|---|---|---|
| `ValueError` | Env var validation | Raise immediately (no log — happens before logger context) | — | Yes |
| `AuthenticationError` | `sharepoint_auth.get_access_token()` | Log structured error, re-raise | ERROR | Yes |
| `SiteNotFoundError` | `client.resolve_site()` | Log structured error, re-raise | ERROR | Yes |
| `DriveNotFoundError` | `client.get_drive_by_name()` | Log structured error, re-raise | ERROR | Yes |
| `GraphFileNotFoundError` | `client.download_file()` | Log structured error, continue to next file | ERROR | No |
| `ClientError` (boto3) | `s3.put_object()` | Log structured error, re-raise | ERROR | Yes |
| `ValueError` | `sharepoint_url_to_graph_path()` | Propagates naturally (no try/except needed) | — | Yes |

### Key Constraint

The `ClientError` try/except must be separate from the `GraphFileNotFoundError` catch. The existing code catches `GraphFileNotFoundError` around both `download_file` and `put_object`. The new design needs to wrap `put_object` in its own try/except for `ClientError` so the structured log can include `bucket` and `object_key`. The simplest approach: nest the `put_object` call inside the existing try block but add a separate `except ClientError` clause.

```python
try:
    response = client.download_file(file.drive_id, file.item_id)
    try:
        s3.put_object(...)
    except ClientError as exc:
        logger.error("S3 upload failed", error_type="S3ClientError",
                     bucket=output_bucket, object_key=object_key, error=str(exc))
        raise
except sharepoint_graph.GraphFileNotFoundError as exc:
    logger.error("Failed to download file", file_name=file.name,
                 error_type="GraphFileNotFoundError", error=str(exc))
    continue
```

## Testing Strategy

### PBT Applicability Assessment

Property-based testing is NOT applicable for this feature. The changes are:
- Replacing one logging library with another (infrastructure swap)
- Adding structured fields to log calls (simple string passthrough)
- Adding try/except blocks that log then re-raise (deterministic behavior)

There are no pure functions with meaningful input variation, no serialization/parsing logic, and no algorithmic behavior where 100 iterations would find more bugs than 2-3 examples. The existing property-based tests (Properties 1-5) for `convert_metadata`, `get_sort_object_key`, CSV parsing, and category filtering remain unchanged and continue to validate the handler's core logic.

### Test Approach

**Unit tests only** — example-based tests for each structured log scenario.

#### Updated Tests (TestLoggingOutput)

The existing `TestLoggingOutput` class (5 tests) must be updated to capture Powertools Logger output instead of using `caplog`:

1. `test_fetching_files_log_includes_drive_name` — verify JSON entry has `drive_name` field
2. `test_moving_files_log_includes_bucket_name` — verify JSON entry has `bucket` field
3. `test_category_skipped_file_no_category_logged` — verify JSON entry has `file_name` and `reason="no Category metadata"`
4. `test_category_skipped_file_prefix_not_in_filter_logged` — verify JSON entry has `file_name`, `category_prefix`, and `reason="category prefix not in filter"`
5. `test_failed_download_logged_with_filename_and_error` — verify JSON entry has `file_name`, `error_type="GraphFileNotFoundError"`, and `error`

#### New Tests (Structured Error Logging)

New tests for error types not previously covered in logging tests:

6. `test_authentication_error_structured_log` — trigger `AuthenticationError`, verify JSON entry has `error_type="AuthenticationError"` and `error`
7. `test_site_not_found_error_structured_log` — trigger `SiteNotFoundError`, verify JSON entry has `error_type="SiteNotFoundError"` and `error`
8. `test_drive_not_found_error_structured_log` — trigger `DriveNotFoundError`, verify JSON entry has `error_type="DriveNotFoundError"`, `drive_name`, and `error`
9. `test_s3_client_error_structured_log` — trigger `ClientError`, verify JSON entry has `error_type="S3ClientError"`, `bucket`, `object_key`, and `error`

#### New Tests (Lambda Context Injection)

10. `test_lambda_context_fields_in_log_entries` — invoke handler with mock Lambda context, verify `function_request_id`, `function_name`, `function_memory_size` in JSON log entries
11. `test_service_name_in_log_entries` — verify `service` field is `"import-documents"` in all log entries

#### Unchanged Tests (Must Pass Without Modification)

- All 5 property-based test classes (Properties 1-5)
- `TestConvertMetadataUnit` (6 tests)
- `TestGetSortObjectKeyUnit` (14 tests)
- `TestEnvVarValidation` (14 tests)
- `TestHandlerOrchestration` (all orchestration tests)
- `TestErrorPropagation` (6 tests)
- `TestModuleInterface` (4 tests)

### Test Runner

```bash
python3 -m pytest tests/test_import_documents.py -v
```
