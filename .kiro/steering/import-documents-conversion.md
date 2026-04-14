---
inclusion: manual
description: Strategic milestones for converting the ImportDocuments C# Lambda to Python and packaging it as a CloudFormation-deployable stack.
---

# ImportDocuments Lambda — C# to Python Conversion Strategy

This document defines the milestones for converting the `ImportDocuments` C# Lambda into a Python Lambda deployable via CloudFormation. Each milestone is scoped to produce a standalone spec.

## Context

The existing C# Lambda (`CS Lambdas/ImportDocuments/`) performs a single job:
1. Authenticate to SharePoint Online (GovCloud) via Azure AD client credentials
2. List files from a SharePoint document library, optionally filtered by folder path and category prefix
3. Copy each file to an S3 bucket, organized into prefix folders by document type (POL, PRO, MSM, WI, MAA, SPS, SSD, STM, or Unknown)
4. Attach document metadata and a `Project=KnowledgeAssistant` tag to each S3 object

The C# version depends on two internal NuGet packages (`AI_Libraries.SharePoint`, `AILibraries.Storage`) that abstract SharePoint Graph API calls and S3 operations. The Python version replaces these with direct API calls using standard libraries.

### Target Environment
- AWS GovCloud (`us-gov-west-1`)
- Azure AD GovCloud (`login.microsoftonline.us`)
- Microsoft Graph GovCloud (`https://graph.microsoft.us/v1.0`)
- SharePoint GovCloud (`.sharepoint.us`)
- Runtime: Python 3.12
- Deployment: CloudFormation (inline or S3-packaged zip)

---

## Milestone 1: SharePoint Authentication Module

**Goal:** Standalone Python module that acquires an OAuth2 access token from Azure AD GovCloud using client credentials flow.

**Scope:**
- Use `msal` library for token acquisition
- Authority URL: `https://login.microsoftonline.us/{tenant_id}`
- Scope: `https://graph.microsoft.us/.default`
- Token caching within a single Lambda invocation (MSAL handles this in-memory)
- Error handling for auth failures (expired secrets, wrong tenant, network issues)

**Inputs:** `tenant_id`, `client_id`, `client_secret` (from environment variables)
**Output:** Bearer token string

**GovCloud gotchas:**
- Authority is `.us` not `.com`
- Graph scope is `graph.microsoft.us` not `graph.microsoft.com`
- The Azure AD app registration must exist in the GovCloud tenant with `Sites.Read.All` application permission (not delegated)

**Dependencies:** None — this is the foundation module.

---

## Milestone 2: SharePoint Graph API Client

**Goal:** Python module that wraps the Microsoft Graph API calls needed to list and download files from a SharePoint document library.

**Scope:**
- Resolve SharePoint site by URL → Graph site ID
  - Convert `https://{host}/sites/{path}` to Graph path `{host}:/sites/{path}`
  - `GET /sites/{siteId}`
- List drives for a site → find drive by name
  - `GET /sites/{siteId}/drives`
- List files in a drive (with optional folder path filter)
  - `GET /drives/{driveId}/root/children` or `/root:/{folderPath}:/children`
  - Handle pagination (`@odata.nextLink`)
  - Extract file metadata (name, path, webUrl, custom metadata columns)
- Download file content as a stream
  - `GET /drives/{driveId}/items/{itemId}/content`

**Inputs:** Bearer token (from Milestone 1), SharePoint URL, drive name, optional folder path
**Output:** Iterator of file objects (name, metadata, content stream)

**GovCloud gotchas:**
- Base URL is `https://graph.microsoft.us/v1.0` not `graph.microsoft.com`
- SharePoint URLs use `.sharepoint.us`

**Dependencies:** Milestone 1 (auth token)

---

## Milestone 3: S3 Upload Logic with Document Sorting

**Goal:** Python module that uploads file content to S3 with the document-type prefix sorting, metadata, and tagging logic from the original C# Lambda.

**Scope:**
- Document type prefix sorting: match filename against known prefixes (`POL`, `PRO`, `MSM`, `WI`, `MAA`, `SPS`, `SSD`, `STM`) → S3 key becomes `{prefix}/{filename}`, defaulting to `Unknown/{filename}`
- Category filtering: parse `csvCategories` env var into a set, skip files whose `Category` metadata (first 3 chars) doesn't match (pass all if set is empty)
- Metadata attachment: convert SharePoint metadata dict to S3 metadata strings, add `Original Document Url`
- Tagging: apply `Project=KnowledgeAssistant` tag
- Use `boto3` `s3.put_object()` directly — no need for the `AILibraries.Storage` abstraction

**Inputs:** S3 bucket name, file name, file content (bytes/stream), metadata dict, category set
**Output:** S3 put_object response

**Dependencies:** None for the module itself, but integrates with Milestone 2 output.

---

## Milestone 4: Lambda Handler Integration

**Goal:** Wire Milestones 1–3 into a single Lambda handler function with proper configuration, logging, and error handling.

**Scope:**
- Environment variable configuration:
  - `clientId`, `clientSecret`, `tenantId` — Azure AD credentials
  - `sharepointUrl` — SharePoint site URL
  - `driveName` — document library name
  - `outputBucket` — target S3 bucket
  - `csvCategories` — comma-separated category filter (optional)
  - `sharePointFolderPath` — subfolder filter (optional)
- Validate all required env vars on startup, fail fast with clear error messages
- Structured logging (use `aws_lambda_powertools` logger per architecture guidelines)
- Handler signature: `def handler(event, context)` returning `"Import Completed"` on success
- Error handling: catch and log SharePoint API errors, S3 errors, auth errors separately

**Inputs:** Lambda event (unused — this is a scheduled/manual trigger), Lambda context
**Output:** `"Import Completed"` string

**Dependencies:** Milestones 1, 2, 3

---

## Milestone 5: CloudFormation Stack

**Goal:** CloudFormation template that deploys the Python Lambda with all supporting resources.

**Scope:**
- `AWS::Lambda::Function` resource:
  - Runtime: `python3.12`
  - Handler: `import_documents.handler`
  - Timeout: 120 seconds (matching current C# config)
  - Memory: 512 MB
  - Architecture: `x86_64`
  - Environment variables: parameterized via stack parameters (secrets via SSM SecureString or Secrets Manager references)
  - VPC configuration: optional, parameterized (current C# Lambda has empty subnet/SG config)
- `AWS::IAM::Role` for Lambda execution:
  - `s3:PutObject`, `s3:PutObjectTagging` on the output bucket
  - CloudWatch Logs permissions
  - VPC permissions if VPC-attached
- Stack parameters for all configurable values (tenant ID, client ID, bucket name, etc.)
- `clientSecret` must NOT be a plain-text parameter — use `AWS::SSM::Parameter::Value<String>` referencing a SecureString parameter, or `AWS::SecretsManager::Secret` with dynamic reference
- Lambda code packaging: S3 bucket + key reference (use pipeline artifacts bucket from `storage-stack`)
- Cross-stack imports: output bucket name/ARN from `storage-stack` if applicable
- Tags: `Environment` and `Project` on all resources

**Dependencies:** Milestones 1–4 (Lambda code must exist), `storage-stack` exports

---

## Milestone 6: Packaging & Deployment

**Goal:** Repeatable process for building, packaging, and deploying the Python Lambda via CloudFormation.

**Scope:**
- `requirements.txt` with pinned dependencies: `msal`, `requests`, `boto3` (boto3 available in Lambda runtime, but pin for reproducibility), `aws-lambda-powertools`
- Build script or Makefile that:
  - Installs dependencies into a `package/` directory
  - Zips the Lambda code + dependencies
  - Uploads the zip to the pipeline artifacts S3 bucket
- Document the deployment commands (`aws cloudformation deploy` or equivalent)
- Validate template with `cfn-lint` before deployment
- Check compliance with `cfn-guard` security rules

**Dependencies:** Milestone 5 (CloudFormation template), pipeline artifacts bucket

---

## Milestone 7: Testing & Validation

**Goal:** Verify the Python Lambda produces identical behavior to the C# version.

**Scope:**
- Unit tests for each module:
  - Auth module: mock MSAL token acquisition, verify GovCloud endpoints
  - Graph client: mock HTTP responses for site resolution, drive listing, file listing, file download
  - S3 upload: mock boto3, verify key sorting logic, metadata mapping, category filtering
- Integration test: run against a real SharePoint site (dev/test tenant) and a test S3 bucket
- Comparison test: run both C# and Python Lambdas against the same SharePoint library, diff the resulting S3 objects (keys, metadata, tags)
- Edge cases to cover:
  - Files with no category metadata
  - Files with unrecognized document type prefixes (→ `Unknown/`)
  - Empty SharePoint folder
  - Large files (memory pressure in Lambda)
  - Pagination (drives with many files)

**Dependencies:** Milestones 1–4 (working Lambda code)

---

## Dependency Graph

```
Milestone 1 (Auth) ──┐
                      ├── Milestone 4 (Handler) ── Milestone 5 (CFN) ── Milestone 6 (Packaging)
Milestone 2 (Graph) ──┤
                      │
Milestone 3 (S3) ─────┘
                                                                         Milestone 7 (Testing)
                                                                         ↑ depends on M1–M4
```

Milestones 1, 2, and 3 can be developed in parallel. Milestone 4 integrates them. Milestones 5 and 6 are sequential. Milestone 7 can begin unit tests as soon as individual modules exist.

---

## What's NOT in Scope

- Modifying the existing C# Lambda — it continues to run as-is until the Python version is validated
- Changing the SharePoint document library structure or metadata schema
- Adding new features (e.g., incremental sync, change detection) — those are separate specs
- EventBridge or Step Functions integration — the current Lambda is manually/schedule triggered; pipeline integration is a separate effort per `deployment-milestones.md`
