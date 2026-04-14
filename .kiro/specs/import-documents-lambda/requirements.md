# Requirements Document

## Introduction

This spec covers Milestone 3 of the ImportDocuments Lambda C#-to-Python conversion: the AWS Lambda handler that orchestrates importing documents from a SharePoint document library into an S3 bucket. The handler reads configuration from environment variables, authenticates with SharePoint via the `sharepoint_auth` module (Milestone 1), uses the `sharepoint_graph` module (Milestone 2) to enumerate and download files, optionally filters files by category metadata, and uploads each file to S3 with metadata and tags.

The Python Lambda replaces `CS Lambdas/ImportDocuments/ImportDocuments/ImportDocuments.cs` and its helper classes `MetadataHelper.cs` and `ObjectKeyHelper.cs`. It reuses the already-built `sharepoint_auth.py` and `sharepoint_graph.py` modules.

## Glossary

- **Lambda_Handler**: The Python function invoked by AWS Lambda as the entry point. Accepts an event and context, returns a result string.
- **Import_Pipeline**: The full orchestration sequence: read config → authenticate → resolve site → find drive → list files → filter → download → upload to S3.
- **Output_Bucket**: The S3 bucket where imported documents are stored, specified by the `outputBucket` environment variable.
- **Category_Filter**: An optional comma-separated list of 3-character category prefixes (from the `csvCategories` environment variable) used to filter files by their `Category` metadata field.
- **Metadata_Converter**: A helper function that converts a `dict[str, object]` of SharePoint file metadata into a `dict[str, str]` suitable for S3 object metadata.
- **Object_Key_Builder**: A helper function that generates the S3 object key by sorting files into prefix folders based on document type codes (e.g., `POL`, `PRO`, `MSM`, `WI`, `MAA`, `SPS`, `SSD`, `STM`), falling back to an `Unknown` prefix.
- **Sorted_Document_Prefixes**: The ordered list of document type codes used for S3 key prefix assignment: `POL`, `PRO`, `MSM`, `WI`, `MAA`, `SPS`, `SSD`, `STM`.
- **S3_Client**: The `boto3` S3 client used to upload files to the Output_Bucket.
- **SharePoint_Auth**: The `sharepoint_auth` module (Milestone 1) that provides `get_access_token()`.
- **Graph_Client**: The `SharePointGraphClient` class from `sharepoint_graph` module (Milestone 2).
- **File_Item**: A dataclass from `sharepoint_graph` representing a file with `name`, `item_id`, `drive_id`, `web_url`, and `metadata` fields.

## Requirements

### Requirement 1: Environment Variable Configuration

**User Story:** As a DevOps engineer deploying the Lambda, I want the Lambda_Handler to read all configuration from environment variables, so that deployment configuration is managed through infrastructure-as-code and not hardcoded.

#### Acceptance Criteria

1. THE Lambda_Handler SHALL read the `clientId` environment variable to obtain the Azure AD application client identifier.
2. THE Lambda_Handler SHALL read the `clientSecret` environment variable to obtain the Azure AD application client secret.
3. THE Lambda_Handler SHALL read the `tenantId` environment variable to obtain the Azure AD tenant identifier.
4. THE Lambda_Handler SHALL read the `sharepointUrl` environment variable to obtain the SharePoint site URL.
5. THE Lambda_Handler SHALL read the `driveName` environment variable to obtain the target document library name.
6. THE Lambda_Handler SHALL read the `outputBucket` environment variable to obtain the S3 destination bucket name.
7. THE Lambda_Handler SHALL read the `csvCategories` environment variable to obtain the optional comma-separated category filter string.
8. THE Lambda_Handler SHALL read the `sharePointFolderPath` environment variable to obtain the optional folder path within the drive.

### Requirement 2: Required Configuration Validation

**User Story:** As a developer troubleshooting Lambda failures, I want the Lambda_Handler to validate that all required configuration values are present before proceeding, so that failures are caught early with clear error messages.

#### Acceptance Criteria

1. IF the `tenantId` environment variable is missing or empty, THEN THE Lambda_Handler SHALL raise a `ValueError` with a message containing `tenantId`.
2. IF the `clientId` environment variable is missing or empty, THEN THE Lambda_Handler SHALL raise a `ValueError` with a message containing `clientId`.
3. IF the `clientSecret` environment variable is missing or empty, THEN THE Lambda_Handler SHALL raise a `ValueError` with a message containing `clientSecret`.
4. IF the `sharepointUrl` environment variable is missing or empty, THEN THE Lambda_Handler SHALL raise a `ValueError` with a message containing `sharepointUrl`.
5. IF the `driveName` environment variable is missing or empty, THEN THE Lambda_Handler SHALL raise a `ValueError` with a message containing `driveName`.
6. IF the `outputBucket` environment variable is missing or empty, THEN THE Lambda_Handler SHALL raise a `ValueError` with a message containing `outputBucket`.
7. WHEN the `csvCategories` environment variable is missing or empty, THE Lambda_Handler SHALL treat the category filter as disabled (import all files).
8. WHEN the `sharePointFolderPath` environment variable is missing or empty, THE Lambda_Handler SHALL use an empty string as the folder path (list files from the drive root).

### Requirement 3: Category Filter Parsing

**User Story:** As a pipeline operator, I want to specify a comma-separated list of category prefixes to filter which documents are imported, so that I can selectively import only relevant document categories.

#### Acceptance Criteria

1. WHEN the `csvCategories` environment variable contains a non-empty comma-separated string, THE Lambda_Handler SHALL parse the string into a set of trimmed, non-empty category prefix strings.
2. WHEN the `csvCategories` string contains entries with leading or trailing whitespace, THE Lambda_Handler SHALL trim whitespace from each entry before adding it to the category set.
3. WHEN the `csvCategories` string contains empty entries (e.g., consecutive commas), THE Lambda_Handler SHALL discard empty entries.
4. WHEN the `csvCategories` environment variable is empty or missing, THE Lambda_Handler SHALL produce an empty category set, indicating no filtering.

### Requirement 4: SharePoint Authentication and Site Resolution

**User Story:** As a developer, I want the Lambda_Handler to authenticate with SharePoint and resolve the target site and drive, so that files can be listed and downloaded.

#### Acceptance Criteria

1. THE Lambda_Handler SHALL call `sharepoint_auth.get_access_token()` to obtain a bearer token for Microsoft Graph API access.
2. THE Lambda_Handler SHALL convert the `sharepointUrl` to a Graph site path using `sharepoint_graph.sharepoint_url_to_graph_path()`.
3. THE Lambda_Handler SHALL create a `SharePointGraphClient` instance using the obtained bearer token.
4. THE Lambda_Handler SHALL call `resolve_site()` on the Graph_Client with the converted Graph site path to obtain the Site ID.
5. THE Lambda_Handler SHALL call `get_drive_by_name()` on the Graph_Client with the Site ID and `driveName` to obtain the target drive.

### Requirement 5: File Listing and Category Filtering

**User Story:** As a pipeline operator, I want the Lambda_Handler to list files from the SharePoint drive and optionally filter them by category, so that only the desired documents are imported into S3.

#### Acceptance Criteria

1. THE Lambda_Handler SHALL call `list_files()` on the Graph_Client with the target drive ID and the optional folder path.
2. WHEN the category set is non-empty and a File_Item has a `Category` key in its metadata, THE Lambda_Handler SHALL extract the first 3 characters of the Category value and check whether the extracted prefix exists in the category set.
3. WHEN the category set is non-empty and the extracted 3-character category prefix is not in the category set, THE Lambda_Handler SHALL skip that file and not upload it to S3.
4. WHEN the category set is empty, THE Lambda_Handler SHALL import all files without category filtering.
5. WHEN a File_Item does not have a `Category` key in its metadata and the category set is non-empty, THE Lambda_Handler SHALL skip that file.

### Requirement 6: Metadata Conversion

**User Story:** As a developer, I want SharePoint file metadata to be converted to S3-compatible string metadata, so that document provenance is preserved in S3.

#### Acceptance Criteria

1. THE Metadata_Converter SHALL accept a `dict[str, object]` and return a `dict[str, str]` where each value is converted to its string representation.
2. WHEN a metadata value is `None`, THE Metadata_Converter SHALL convert the value to an empty string `""`.
3. THE Lambda_Handler SHALL add an `Original Document Url` key to the converted metadata with the value set to the File_Item `web_url` field.
4. FOR ALL input dictionaries, converting metadata and then checking that every output value is a `str` SHALL hold true (type invariant).

### Requirement 7: S3 Object Key Generation

**User Story:** As a pipeline operator, I want imported documents to be organized into S3 prefix folders by document type, so that the bucket structure is navigable and consistent with the existing C# Lambda behavior.

#### Acceptance Criteria

1. THE Object_Key_Builder SHALL accept a file name and return an S3 object key in the format `{prefix}/{filename}`.
2. WHEN the file name starts with one of the Sorted_Document_Prefixes (`POL`, `PRO`, `MSM`, `WI`, `MAA`, `SPS`, `SSD`, `STM`), THE Object_Key_Builder SHALL use the first matching prefix as the folder prefix.
3. WHEN the file name does not start with any of the Sorted_Document_Prefixes, THE Object_Key_Builder SHALL use `Unknown` as the folder prefix.
4. THE Object_Key_Builder SHALL check the Sorted_Document_Prefixes in the defined order and use the first match.
5. FOR ALL file names, the Object_Key_Builder SHALL produce an object key that contains exactly one `/` separator between the prefix and the file name (structural invariant).

### Requirement 8: S3 Upload with Metadata and Tags

**User Story:** As a developer, I want each imported document to be uploaded to S3 with its converted metadata and a project tag, so that documents are traceable and tagged for the KnowledgeAssistant project.

#### Acceptance Criteria

1. THE Lambda_Handler SHALL upload each file to the Output_Bucket using the S3_Client `put_object` operation.
2. THE Lambda_Handler SHALL set the S3 object key to the value produced by the Object_Key_Builder for the file name.
3. THE Lambda_Handler SHALL attach the converted metadata dictionary (including the `Original Document Url` entry) as S3 object metadata on the uploaded object.
4. THE Lambda_Handler SHALL attach a tag with key `Project` and value `KnowledgeAssistant` to each uploaded object.
5. WHEN a folder path is specified, THE Lambda_Handler SHALL prepend the folder path to the file name before passing it to the Object_Key_Builder.
6. THE Lambda_Handler SHALL download the file content from SharePoint as a stream and upload the stream content to S3.

### Requirement 9: Lambda Handler Interface and Return Value

**User Story:** As a developer integrating the Lambda into the pipeline, I want the handler to follow the standard AWS Lambda Python handler signature and return a completion message, so that it integrates with the existing orchestration infrastructure.

#### Acceptance Criteria

1. THE Lambda_Handler SHALL be a function named `handler` that accepts two parameters: `event` and `context`.
2. WHEN the import process completes successfully, THE Lambda_Handler SHALL return the string `"Import Completed"`.
3. IF an unhandled exception occurs during the import process, THE Lambda_Handler SHALL allow the exception to propagate to the Lambda runtime (no silent swallowing of errors).

### Requirement 10: Error Handling for SharePoint Operations

**User Story:** As a developer, I want clear error propagation when SharePoint operations fail, so that I can diagnose issues with authentication, site resolution, drive lookup, or file access.

#### Acceptance Criteria

1. IF `sharepoint_auth.get_access_token()` raises an `AuthenticationError`, THEN THE Lambda_Handler SHALL allow the exception to propagate.
2. IF `sharepoint_graph.sharepoint_url_to_graph_path()` raises a `ValueError`, THEN THE Lambda_Handler SHALL allow the exception to propagate.
3. IF `resolve_site()` raises a `SiteNotFoundError`, THEN THE Lambda_Handler SHALL allow the exception to propagate.
4. IF `get_drive_by_name()` raises a `DriveNotFoundError`, THEN THE Lambda_Handler SHALL allow the exception to propagate.
5. IF `download_file()` raises a `GraphFileNotFoundError` for a specific file, THEN THE Lambda_Handler SHALL log the error and continue processing remaining files.
6. IF the S3_Client `put_object` call fails, THEN THE Lambda_Handler SHALL allow the exception to propagate.

### Requirement 11: Logging

**User Story:** As a developer monitoring the Lambda in CloudWatch, I want the handler to log key events during the import process, so that I can trace execution and diagnose issues.

#### Acceptance Criteria

1. THE Lambda_Handler SHALL log a message when starting the file listing phase, including the drive name.
2. THE Lambda_Handler SHALL log a message when starting the S3 upload phase, including the Output_Bucket name.
3. THE Lambda_Handler SHALL log a message for each file that is skipped due to category filtering.
4. IF a file download fails, THEN THE Lambda_Handler SHALL log the file name and the error details.
5. THE Lambda_Handler SHALL use Python standard `logging` module for all log output.

### Requirement 12: Module Structure

**User Story:** As a developer maintaining the codebase, I want the Lambda handler and its helpers to be organized in a single file with clear separation of concerns, so that the code is easy to navigate and test.

#### Acceptance Criteria

1. THE Lambda handler, Metadata_Converter, and Object_Key_Builder SHALL reside in a single Python file named `import_documents.py`.
2. THE Metadata_Converter SHALL be a standalone function that can be called independently of the Lambda_Handler.
3. THE Object_Key_Builder SHALL be a standalone function that can be called independently of the Lambda_Handler.
4. THE `import_documents.py` module SHALL import `sharepoint_auth` and `sharepoint_graph` as dependencies.
5. THE `import_documents.py` module SHALL import `boto3` for S3 operations.
