"""ImportDocuments Lambda handler for SharePoint-to-S3 document import.

Orchestrates importing documents from a SharePoint document library into
an S3 bucket. Reads configuration from environment variables, authenticates
with SharePoint via the sharepoint_auth module, uses the sharepoint_graph
module to enumerate and download files, optionally filters files by category
metadata, converts metadata to S3-compatible strings, generates S3 object
keys with document-type prefix sorting, and uploads each file to S3 with
metadata and tags.

This is Milestone 3 of the ImportDocuments C#-to-Python conversion,
replacing ImportDocuments.cs, MetadataHelper.cs, and ObjectKeyHelper.cs.
"""

import os
import posixpath

import boto3
from aws_lambda_powertools import Logger
from botocore.exceptions import ClientError

import sharepoint_auth
import sharepoint_graph

logger = Logger(service="import-documents")

SORTED_DOCUMENT_PREFIXES: list[str] = [
    "POL", "PRO", "MSM", "WI", "MAA", "SPS", "SSD", "STM"
]


def convert_metadata(metadata: dict[str, object] | None) -> dict[str, str]:
    """Convert SharePoint file metadata to S3-compatible string metadata.

    Args:
        metadata: Dictionary of metadata key-value pairs from SharePoint.
                  Values may be any type. May be None.

    Returns:
        A new dict[str, str] where each value is converted via str(),
        with None values becoming empty strings.
    """
    if metadata is None:
        return {}
    return {key: str(value) if value is not None else "" for key, value in metadata.items()}


def get_sort_object_key(filename: str) -> str:
    """Generate an S3 object key with document-type prefix sorting.

    Iterates SORTED_DOCUMENT_PREFIXES in order and returns
    "{prefix}/{filename}" for the first matching prefix. If no prefix
    matches, returns "Unknown/{filename}".

    Args:
        filename: The file name (e.g., "POL-001 Policy Document.pdf").

    Returns:
        S3 object key like "{prefix}/{filename}" where prefix is the
        first matching document type code, or "Unknown" if no match.
    """
    for prefix in SORTED_DOCUMENT_PREFIXES:
        if filename.startswith(prefix):
            return f"{prefix}/{filename}"
    return f"Unknown/{filename}"


@logger.inject_lambda_context
def handler(event, context) -> str:
    """AWS Lambda handler for importing SharePoint documents to S3.

    Reads configuration from environment variables, authenticates with
    SharePoint, lists files from the target drive, optionally filters
    by category, and uploads each file to S3 with metadata and tags.

    Args:
        event: Lambda event (unused — handler is triggered on schedule
               or manually).
        context: Lambda context object.

    Returns:
        "Import Completed" on success.

    Raises:
        ValueError: If a required environment variable is missing or empty.
        AuthenticationError: If SharePoint authentication fails.
        SiteNotFoundError: If the SharePoint site cannot be resolved.
        DriveNotFoundError: If the target drive is not found.
        ClientError: If an S3 upload fails.
    """
    # 1. Read all 8 environment variables
    client_id = os.environ.get("clientId", "")
    client_secret = os.environ.get("clientSecret", "")
    tenant_id = os.environ.get("tenantId", "")
    sharepoint_url = os.environ.get("sharepointUrl", "")
    drive_name = os.environ.get("driveName", "")
    output_bucket = os.environ.get("outputBucket", "")
    csv_categories = os.environ.get("csvCategories", "")
    folder_path = os.environ.get("sharePointFolderPath", "")

    # 2. Validate 6 required variables
    required = {
        "clientId": client_id,
        "clientSecret": client_secret,
        "tenantId": tenant_id,
        "sharepointUrl": sharepoint_url,
        "driveName": drive_name,
        "outputBucket": output_bucket,
    }
    for var_name, var_value in required.items():
        if not var_value:
            raise ValueError(
                f"Missing required environment variable: {var_name}"
            )

    # 3. Parse csvCategories into a set of trimmed, non-empty strings
    categories: set[str] = set()
    if csv_categories:
        categories = {
            entry.strip()
            for entry in csv_categories.split(",")
            if entry.strip()
        }

    # 4. sharePointFolderPath defaults to "" (already handled by os.environ.get)

    # 5. Authenticate with SharePoint
    try:
        token = sharepoint_auth.get_access_token()
    except sharepoint_auth.AuthenticationError as exc:
        logger.error("Authentication failed", error_type="AuthenticationError", error=str(exc))
        raise

    # 6. Convert SharePoint URL to Graph API site path
    graph_site_path = sharepoint_graph.sharepoint_url_to_graph_path(
        sharepoint_url
    )

    # 7. Create Graph client and orchestrate import
    s3 = boto3.client("s3")

    with sharepoint_graph.SharePointGraphClient(token) as client:
        # 8. Resolve site and drive
        try:
            site_id = client.resolve_site(graph_site_path)
        except sharepoint_graph.SiteNotFoundError as exc:
            logger.error("Site resolution failed", error_type="SiteNotFoundError", error=str(exc))
            raise
        try:
            drive = client.get_drive_by_name(site_id, drive_name)
        except sharepoint_graph.DriveNotFoundError as exc:
            logger.error("Drive lookup failed", error_type="DriveNotFoundError", drive_name=drive_name, error=str(exc))
            raise

        # 9. List files
        logger.info("Fetching files from SharePoint", drive_name=drive_name)
        files = client.list_files(drive.drive_id, folder_path)

        # 10. Upload files to S3
        logger.info("Moving files to S3", bucket=output_bucket)

        for file in files:
            # Apply category filter
            if categories:
                file_category = file.metadata.get("Category")
                if file_category is None:
                    logger.info("Skipping file", file_name=file.name, reason="no Category metadata")
                    continue
                prefix_3 = str(file_category)[:3]
                if prefix_3 not in categories:
                    logger.info("Skipping file", file_name=file.name, category_prefix=prefix_3, reason="category prefix not in filter")
                    continue

            # Build file path
            file_path = (
                posixpath.join(folder_path, file.name)
                if folder_path
                else file.name
            )

            # Convert metadata and add Original Document Url
            metadata = convert_metadata(file.metadata)
            metadata["Original Document Url"] = file.web_url

            # Generate S3 object key
            object_key = get_sort_object_key(file_path)

            # Download and upload
            try:
                response = client.download_file(file.drive_id, file.item_id)
                try:
                    s3.put_object(
                        Bucket=output_bucket,
                        Key=object_key,
                        Body=response.content,
                        Metadata=metadata,
                        Tagging="Project=KnowledgeAssistant",
                    )
                except ClientError as exc:
                    logger.error("S3 upload failed", error_type="S3ClientError", bucket=output_bucket, object_key=object_key, error=str(exc))
                    raise
            except sharepoint_graph.GraphFileNotFoundError as exc:
                logger.error("Failed to download file", file_name=file.name, error_type="GraphFileNotFoundError", error=str(exc))
                continue

    return "Import Completed"
