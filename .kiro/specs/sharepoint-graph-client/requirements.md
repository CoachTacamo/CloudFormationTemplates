# Requirements Document

## Introduction

Python module (`sharepoint_graph.py`) that wraps the Microsoft Graph API calls needed to list and download files from a SharePoint document library in Azure GovCloud. This module is Milestone 2 of the ImportDocuments C#-to-Python conversion and depends on the bearer token produced by the `sharepoint_auth` module (Milestone 1). All Graph API calls target the GovCloud endpoint (`https://graph.microsoft.us/v1.0`).

## Glossary

- **Graph_Client**: The top-level Python class that orchestrates SharePoint Graph API operations. Accepts a bearer token and base URL, exposes methods for site resolution, drive listing, file listing, and file download.
- **Graph_Base_URL**: The root URL for Microsoft Graph API requests. Defaults to `https://graph.microsoft.us/v1.0` for GovCloud.
- **Site_ID**: The opaque identifier returned by the Graph API for a SharePoint site (e.g., `contoso.sharepoint.us,guid,guid`).
- **Drive_ID**: The opaque identifier returned by the Graph API for a SharePoint document library (drive).
- **Item_ID**: The opaque identifier returned by the Graph API for a file (drive item).
- **SharePoint_URL**: A user-facing SharePoint site URL in the form `https://{host}/sites/{path}`.
- **Graph_Site_Path**: The Graph API site-addressing format `{host}:/sites/{path}` derived from a SharePoint_URL.
- **File_Item**: A Python dataclass or typed dict representing a file returned by the listing endpoint, containing at minimum: name, item ID, drive ID, web URL, and a metadata dictionary.
- **Pagination**: The Graph API pattern where large result sets are split across multiple responses linked by an `@odata.nextLink` URL.
- **URL_Converter**: A pure function that transforms a SharePoint_URL into a Graph_Site_Path.

## Requirements

### Requirement 1: SharePoint URL to Graph Site Path Conversion

**User Story:** As a developer, I want to convert a user-facing SharePoint URL into the Graph API site-addressing format, so that I can resolve the site via the Graph API.

#### Acceptance Criteria

1. WHEN a valid SharePoint_URL in the form `https://{host}/sites/{path}` is provided, THE URL_Converter SHALL return a Graph_Site_Path in the form `{host}:/sites/{path}`.
2. WHEN a SharePoint_URL contains a trailing slash, THE URL_Converter SHALL strip the trailing slash before conversion.
3. WHEN a SharePoint_URL contains additional path segments after the site path (e.g., `/sites/path/subsite`), THE URL_Converter SHALL preserve all segments after `/sites/` in the Graph_Site_Path.
4. IF a SharePoint_URL does not contain a `/sites/` segment, THEN THE URL_Converter SHALL raise a ValueError with a message indicating the URL format is invalid.
5. IF a SharePoint_URL is empty or None, THEN THE URL_Converter SHALL raise a ValueError.
6. FOR ALL valid SharePoint_URLs, converting to Graph_Site_Path and then reconstructing the original URL by prepending `https://` and replacing `:/sites/` with `/sites/` SHALL produce the original URL without trailing slash (round-trip property).

### Requirement 2: Site Resolution

**User Story:** As a developer, I want to resolve a SharePoint site by its Graph site path, so that I can obtain the Site_ID needed for subsequent API calls.

#### Acceptance Criteria

1. WHEN a valid Graph_Site_Path is provided, THE Graph_Client SHALL send a GET request to `{Graph_Base_URL}/sites/{Graph_Site_Path}` with the bearer token in the Authorization header.
2. WHEN the Graph API returns a successful response containing an `id` field, THE Graph_Client SHALL return the `id` value as the Site_ID.
3. IF the Graph API returns an HTTP 404 status, THEN THE Graph_Client SHALL raise a specific error indicating the site was not found.
4. IF the Graph API returns any other HTTP error status (4xx or 5xx), THEN THE Graph_Client SHALL raise an error containing the HTTP status code and the error message from the response body.

### Requirement 3: Drive Listing

**User Story:** As a developer, I want to list all drives for a SharePoint site and find a specific drive by name, so that I can target the correct document library.

#### Acceptance Criteria

1. WHEN a valid Site_ID is provided, THE Graph_Client SHALL send a GET request to `{Graph_Base_URL}/sites/{Site_ID}/drives` with the bearer token in the Authorization header.
2. WHEN the Graph API returns a successful response containing a `value` array of drive objects, THE Graph_Client SHALL return a list of drive records each containing at minimum the drive ID and drive name.
3. WHEN a drive name is provided to a lookup method, THE Graph_Client SHALL return the drive record whose name matches the provided name (case-sensitive).
4. IF no drive matches the provided name, THEN THE Graph_Client SHALL raise an error indicating the drive was not found, including the requested name in the error message.
5. IF the Graph API returns an HTTP error status, THEN THE Graph_Client SHALL raise an error containing the HTTP status code and the error message from the response body.

### Requirement 4: File Listing

**User Story:** As a developer, I want to list files in a SharePoint drive with optional folder path filtering, so that I can enumerate documents for import.

#### Acceptance Criteria

1. WHEN a Drive_ID is provided without a folder path, THE Graph_Client SHALL send a GET request to `{Graph_Base_URL}/drives/{Drive_ID}/root/children` with the bearer token in the Authorization header.
2. WHEN a Drive_ID is provided with a non-empty folder path, THE Graph_Client SHALL send a GET request to `{Graph_Base_URL}/drives/{Drive_ID}/root:/{folder_path}:/children` with the bearer token in the Authorization header.
3. WHEN the Graph API response contains a `value` array, THE Graph_Client SHALL yield a File_Item for each entry that represents a file (has a `file` facet), containing the item name, Item_ID, Drive_ID, web URL, and a metadata dictionary extracted from the `listItem.fields` property.
4. WHEN the Graph API response contains an `@odata.nextLink` field, THE Graph_Client SHALL follow the next-link URL to fetch subsequent pages and continue yielding File_Item records until no more next-links remain.
5. WHEN the Graph API response contains entries that represent folders (have a `folder` facet instead of a `file` facet), THE Graph_Client SHALL skip those entries and not yield them as File_Item records.
6. IF the Graph API returns an HTTP error status on any page request, THEN THE Graph_Client SHALL raise an error containing the HTTP status code and the error message from the response body.
7. THE Graph_Client SHALL include `$expand=listItem($expand=fields)` as a query parameter in file listing requests to retrieve custom metadata columns.

### Requirement 5: File Download

**User Story:** As a developer, I want to download file content as a byte stream, so that I can transfer the file to S3 without loading the entire file into memory.

#### Acceptance Criteria

1. WHEN a Drive_ID and Item_ID are provided, THE Graph_Client SHALL send a GET request to `{Graph_Base_URL}/drives/{Drive_ID}/items/{Item_ID}/content` with the bearer token in the Authorization header and streaming enabled.
2. WHEN the Graph API returns a successful response, THE Graph_Client SHALL return the response as a readable byte stream without buffering the entire content in memory.
3. IF the Graph API returns an HTTP 404 status, THEN THE Graph_Client SHALL raise an error indicating the file was not found.
4. IF the Graph API returns any other HTTP error status, THEN THE Graph_Client SHALL raise an error containing the HTTP status code and the error message from the response body.

### Requirement 6: GovCloud Endpoint Enforcement

**User Story:** As a developer, I want all Graph API calls to target GovCloud endpoints exclusively, so that the module is safe for use in GovCloud environments.

#### Acceptance Criteria

1. THE Graph_Client SHALL default the Graph_Base_URL to `https://graph.microsoft.us/v1.0`.
2. THE Graph_Client SHALL accept an optional Graph_Base_URL parameter at construction time to allow overriding the default for testing purposes.
3. FOR ALL HTTP requests made by the Graph_Client, the request URL SHALL start with the configured Graph_Base_URL, except when following an `@odata.nextLink` URL provided by the Graph API.
4. WHEN following an `@odata.nextLink` URL, THE Graph_Client SHALL use the URL as-is (the Graph API returns fully-qualified URLs that already include the correct host).

### Requirement 7: HTTP Session and Authentication

**User Story:** As a developer, I want the Graph client to manage HTTP sessions and authentication headers efficiently, so that connections are reused and every request is authenticated.

#### Acceptance Criteria

1. THE Graph_Client SHALL accept a bearer token string at construction time and include it as `Authorization: Bearer {token}` in every HTTP request.
2. THE Graph_Client SHALL use a persistent HTTP session (e.g., `requests.Session`) to enable connection reuse across multiple API calls.
3. THE Graph_Client SHALL support use as a context manager (`with` statement) to ensure the HTTP session is properly closed on exit.

### Requirement 8: Error Types

**User Story:** As a developer, I want distinct error types for different failure modes, so that callers can handle errors appropriately.

#### Acceptance Criteria

1. THE module SHALL define a `SharePointGraphError` base exception class with attributes for HTTP status code and error message.
2. THE module SHALL define a `SiteNotFoundError` subclass of `SharePointGraphError` for HTTP 404 responses on site resolution.
3. THE module SHALL define a `DriveNotFoundError` exception for when a requested drive name does not exist in the drives list.
4. THE module SHALL define a `FileNotFoundError` subclass of `SharePointGraphError` for HTTP 404 responses on file download (note: this shadows the built-in; use a module-qualified name or a distinct name like `GraphFileNotFoundError`).
5. WHEN the Graph API returns an error response with a JSON body containing an `error.message` field, THE Graph_Client SHALL include that message in the raised exception.
