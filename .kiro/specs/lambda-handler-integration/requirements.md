# Requirements Document

## Introduction

Milestone 4 of the ImportDocuments C#-to-Python conversion upgrades the existing `import_documents.py` Lambda handler to use AWS Lambda Powertools structured logging instead of Python's standard `logging` module. The handler already works — it reads environment variables, authenticates with SharePoint, lists and filters files, and uploads them to S3. This milestone replaces the logging infrastructure with `aws_lambda_powertools.Logger`, adds structured log fields (correlation IDs, service name, error categories), and ensures error handling logs errors with proper structure before propagation. No functional behavior changes — only the logging mechanism and error observability are upgraded.

## Glossary

- **Handler**: The `handler(event, context)` function in `import_documents.py` that serves as the AWS Lambda entry point.
- **Logger**: An instance of `aws_lambda_powertools.Logger` configured with a service name, used for structured JSON logging.
- **Lambda_Context**: The AWS Lambda context object passed as the second argument to the handler, containing request ID, function name, memory limit, and other invocation metadata.
- **Structured_Log**: A JSON-formatted log entry emitted by the Logger, containing key-value fields beyond the log message (e.g., service name, correlation ID, extra data).
- **Correlation_ID**: A unique identifier (typically the Lambda request ID) included in every log entry to trace all logs from a single invocation.
- **Inject_Lambda_Context**: The `@logger.inject_lambda_context` decorator from Lambda Powertools that automatically adds Lambda invocation metadata (request ID, function name, function version, memory limit) to every log entry for the decorated function.
- **Service_Name**: A string identifier (e.g., `"import-documents"`) set on the Logger to identify which service produced a log entry, configurable via the `POWERTOOLS_SERVICE_NAME` environment variable or the `service` constructor parameter.
- **AuthenticationError**: Exception raised by `sharepoint_auth` when Azure AD token acquisition fails.
- **SiteNotFoundError**: Exception raised by `sharepoint_graph` when SharePoint site resolution returns HTTP 404.
- **DriveNotFoundError**: Exception raised by `sharepoint_graph` when the target drive name is not found.
- **GraphFileNotFoundError**: Exception raised by `sharepoint_graph` when a file download returns HTTP 404.
- **ClientError**: Exception raised by `boto3` when an S3 API call fails.

## Requirements

### Requirement 1: Replace Standard Logging with Lambda Powertools Logger

**User Story:** As a DevOps engineer, I want the ImportDocuments Lambda to use `aws_lambda_powertools.Logger` for structured JSON logging, so that logs are machine-parseable and consistent with the pipeline's observability standards.

#### Acceptance Criteria

1. THE Handler module SHALL import `Logger` from `aws_lambda_powertools` instead of using Python's standard `logging` module.
2. THE Handler module SHALL create a module-level Logger instance with the Service_Name set to `"import-documents"`.
3. THE Logger instance SHALL be configurable via the `POWERTOOLS_SERVICE_NAME` environment variable, falling back to the hardcoded `"import-documents"` default when the environment variable is not set.
4. THE Handler module SHALL NOT import or use Python's standard `logging.getLogger()` for any operational logging.

### Requirement 2: Inject Lambda Context into Logs

**User Story:** As a DevOps engineer, I want every log entry from a handler invocation to include the Lambda request ID and function metadata, so that I can correlate logs to specific invocations.

#### Acceptance Criteria

1. THE Handler function SHALL be decorated with `@logger.inject_lambda_context` to automatically inject Lambda_Context fields into every log entry.
2. WHEN the Handler is invoked, THE Logger SHALL include the Lambda request ID as a Correlation_ID in every Structured_Log entry emitted during that invocation.
3. WHEN the Handler is invoked, THE Logger SHALL include the function name, function version, and memory limit from the Lambda_Context in log entries.

### Requirement 3: Structured Logging for File Listing Phase

**User Story:** As a DevOps engineer, I want the file listing log entry to include structured fields for the drive name, so that I can filter and search logs by drive.

#### Acceptance Criteria

1. WHEN the Handler begins fetching files from SharePoint, THE Logger SHALL emit an info-level Structured_Log entry that includes the drive name as a named field.
2. THE Structured_Log entry for the file listing phase SHALL include the drive name as a key-value pair accessible for log filtering, not only embedded in the message string.

### Requirement 4: Structured Logging for S3 Upload Phase

**User Story:** As a DevOps engineer, I want the S3 upload log entry to include structured fields for the output bucket name, so that I can filter logs by target bucket.

#### Acceptance Criteria

1. WHEN the Handler begins uploading files to S3, THE Logger SHALL emit an info-level Structured_Log entry that includes the output bucket name as a named field.
2. THE Structured_Log entry for the S3 upload phase SHALL include the bucket name as a key-value pair accessible for log filtering, not only embedded in the message string.

### Requirement 5: Structured Logging for Skipped Files

**User Story:** As a DevOps engineer, I want skipped-file log entries to include structured fields for the file name and skip reason, so that I can programmatically identify which files were filtered and why.

#### Acceptance Criteria

1. WHEN a file is skipped because the metadata does not contain a Category key, THE Logger SHALL emit an info-level Structured_Log entry that includes the file name and the reason `"no Category metadata"` as named fields.
2. WHEN a file is skipped because the category prefix is not in the filter set, THE Logger SHALL emit an info-level Structured_Log entry that includes the file name, the category prefix, and the reason `"category prefix not in filter"` as named fields.

### Requirement 6: Structured Error Logging for Authentication Failures

**User Story:** As a DevOps engineer, I want authentication errors to be logged with structured fields before propagation, so that I can quickly identify auth failures in log queries.

#### Acceptance Criteria

1. WHEN an AuthenticationError occurs during token acquisition, THE Handler SHALL log an error-level Structured_Log entry that includes the error type `"AuthenticationError"` and the error message as named fields.
2. WHEN an AuthenticationError occurs, THE Handler SHALL propagate the original exception after logging the structured error entry.

### Requirement 7: Structured Error Logging for Site Resolution Failures

**User Story:** As a DevOps engineer, I want site resolution errors to be logged with structured fields before propagation, so that I can distinguish site errors from other failure types.

#### Acceptance Criteria

1. WHEN a SiteNotFoundError occurs during site resolution, THE Handler SHALL log an error-level Structured_Log entry that includes the error type `"SiteNotFoundError"` and the error message as named fields.
2. WHEN a SiteNotFoundError occurs, THE Handler SHALL propagate the original exception after logging the structured error entry.

### Requirement 8: Structured Error Logging for Drive Lookup Failures

**User Story:** As a DevOps engineer, I want drive lookup errors to be logged with structured fields before propagation, so that I can identify misconfigured drive names.

#### Acceptance Criteria

1. WHEN a DriveNotFoundError occurs during drive lookup, THE Handler SHALL log an error-level Structured_Log entry that includes the error type `"DriveNotFoundError"`, the drive name, and the error message as named fields.
2. WHEN a DriveNotFoundError occurs, THE Handler SHALL propagate the original exception after logging the structured error entry.

### Requirement 9: Structured Error Logging for File Download Failures

**User Story:** As a DevOps engineer, I want file download errors to be logged with structured fields, so that I can identify which specific files failed to download.

#### Acceptance Criteria

1. WHEN a GraphFileNotFoundError occurs during file download, THE Logger SHALL emit an error-level Structured_Log entry that includes the file name, the error type `"GraphFileNotFoundError"`, and the error message as named fields.
2. WHEN a GraphFileNotFoundError occurs for a single file, THE Handler SHALL continue processing remaining files without propagating the exception.

### Requirement 10: Structured Error Logging for S3 Upload Failures

**User Story:** As a DevOps engineer, I want S3 upload errors to be logged with structured fields before propagation, so that I can identify which bucket or key caused the failure.

#### Acceptance Criteria

1. WHEN a ClientError occurs during S3 upload, THE Handler SHALL log an error-level Structured_Log entry that includes the error type `"S3ClientError"`, the bucket name, the object key, and the error message as named fields.
2. WHEN a ClientError occurs during S3 upload, THE Handler SHALL propagate the original exception after logging the structured error entry.

### Requirement 11: Preserve Existing Handler Behavior

**User Story:** As a developer, I want the logging upgrade to not change any functional behavior of the handler, so that existing tests for env var validation, orchestration, and return values continue to pass.

#### Acceptance Criteria

1. THE Handler SHALL continue to validate all 6 required environment variables (`clientId`, `clientSecret`, `tenantId`, `sharepointUrl`, `driveName`, `outputBucket`) and raise ValueError with the variable name when any is missing or empty.
2. THE Handler SHALL continue to accept the `handler(event, context)` signature and return `"Import Completed"` on success.
3. THE Handler SHALL continue to propagate AuthenticationError, SiteNotFoundError, DriveNotFoundError, and ClientError exceptions to the caller after logging.
4. THE Handler SHALL continue to skip individual files on GraphFileNotFoundError and process remaining files.
5. THE `convert_metadata` and `get_sort_object_key` functions SHALL remain unchanged in behavior and interface.

### Requirement 12: Test Compatibility with Powertools Logger

**User Story:** As a developer, I want the existing test suite to be updated to work with the Powertools Logger, so that all tests continue to validate handler behavior after the logging upgrade.

#### Acceptance Criteria

1. WHEN tests verify log output, THE test suite SHALL capture Structured_Log entries from the Powertools Logger rather than from the standard `logging` module.
2. THE test suite SHALL verify that structured error log entries contain the expected error type and message fields.
3. THE test suite SHALL verify that structured info log entries for file listing and S3 upload phases contain the expected named fields.
4. THE test suite SHALL continue to pass all existing property-based tests and unit tests for `convert_metadata`, `get_sort_object_key`, CSV category parsing, category filtering, env var validation, handler orchestration, error propagation, and module interface without modification to those tests.
