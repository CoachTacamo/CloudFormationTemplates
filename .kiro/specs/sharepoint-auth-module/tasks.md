# Implementation Plan: SharePoint Auth Module

## Overview

Implement `sharepoint_auth.py` — a single-file Python module that acquires OAuth2 access tokens from Azure AD GovCloud using the MSAL client credentials flow. The module provides `create_auth_client()` and `get_access_token()` entry points, a custom `AuthenticationError` exception, and GovCloud-only endpoint constants. All tests mock MSAL — no real Azure AD calls.

## Tasks

- [x] 1. Create module file with constants and exception class
  - [x] 1.1 Create `sharepoint_auth.py` with module-level constants and imports
    - Import `os` and `msal`
    - Define `GOVCLOUD_AUTHORITY_HOST = "login.microsoftonline.us"`
    - Define `GOVCLOUD_GRAPH_SCOPE = ["https://graph.microsoft.us/.default"]`
    - Define module-level `_client: msal.ConfidentialClientApplication | None = None`
    - _Requirements: 7.1, 7.2, 7.4, 8.2, 8.3_

  - [x] 1.2 Implement `AuthenticationError` exception class
    - Extend `Exception`
    - Store `error` and `error_description` as instance attributes
    - Format message as `"{error}: {error_description}"`
    - _Requirements: 5.1, 6.4_

- [-] 2. Implement `create_auth_client()` factory function
  - [x] 2.1 Implement `create_auth_client(tenant_id, client_id, client_secret)`
    - Construct authority URL as `https://{GOVCLOUD_AUTHORITY_HOST}/{tenant_id}`
    - Create and return `msal.ConfidentialClientApplication` with provided credentials and authority
    - No network calls — MSAL defers token acquisition
    - _Requirements: 1.1, 1.2, 1.3, 6.2_

  - [x] 2.2 Write property test: Auth client configuration preserves credentials and uses GovCloud authority
    - **Property 1: Auth client configuration preserves credentials and uses GovCloud authority**
    - Generate random (tenant_id, client_id, client_secret) tuples with Hypothesis
    - Mock `msal.ConfidentialClientApplication`, verify authority URL equals `https://login.microsoftonline.us/{tenant_id}` and credentials match
    - **Validates: Requirements 1.1, 1.2**

  - [x] 2.3 Write property test: GovCloud-only endpoint enforcement
    - **Property 4: GovCloud-only endpoint enforcement**
    - Generate random tenant_id strings (including adversarial ones containing "login.microsoftonline.com")
    - Verify constructed authority URL never contains `login.microsoftonline.com` or `graph.microsoft.com`
    - Verify `GOVCLOUD_GRAPH_SCOPE` contains no commercial domain strings
    - **Validates: Requirements 1.3, 2.4, 7.1, 7.2, 7.3**

- [-] 3. Implement `get_access_token()` convenience function
  - [x] 3.1 Implement environment variable reading and validation
    - Read `tenantId`, `clientId`, `clientSecret` from `os.environ`
    - Raise `ValueError` with message `Missing required environment variable: {name}` if any is missing or empty
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 3.2 Implement token acquisition with two-step cache-first pattern
    - On first call: initialize module-level `_client` via `create_auth_client()`
    - Call `acquire_token_silent_with_error(GOVCLOUD_GRAPH_SCOPE, account=None)` first
    - On cache miss (`None`): call `acquire_token_for_client(GOVCLOUD_GRAPH_SCOPE)`
    - If result contains `access_token`: return it
    - If result contains `error`: raise `AuthenticationError` with error details
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 5.1, 6.1, 6.3_

  - [x] 3.3 Write property test: Successful token extraction
    - **Property 2: Successful token extraction**
    - Generate random non-empty access_token strings with Hypothesis
    - Mock MSAL to return success responses, verify `get_access_token()` returns the exact token string unchanged
    - **Validates: Requirements 2.3**

  - [x] 3.4 Write property test: Error response raises AuthenticationError with matching fields
    - **Property 3: Error response raises AuthenticationError with matching fields**
    - Generate random error/error_description string pairs with Hypothesis
    - Mock MSAL to return error responses, verify `AuthenticationError` attributes match exactly
    - **Validates: Requirements 5.1, 5.3, 5.4**

  - [x] 3.5 Write property test: Missing environment variable validation
    - **Property 5: Missing environment variable validation**
    - For each of the three required env vars, generate random empty/missing states
    - Verify `ValueError` is raised with the correct variable name in the message
    - **Validates: Requirements 4.4, 4.5, 4.6**

- [x] 4. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [-] 5. Write unit tests for behavioral requirements
  - [x] 5.1 Write unit tests for cache-first behavior and singleton pattern
    - Test that `acquire_token_silent_with_error` is called before `acquire_token_for_client` (Req 2.1)
    - Test that cache hit skips `acquire_token_for_client` call (Req 3.2)
    - Test that `_client` is reused across multiple `get_access_token()` calls (Req 3.1)
    - Test auto-initialization from env vars when `_client` is None (Req 6.3)
    - _Requirements: 2.1, 3.1, 3.2, 6.3_

  - [x] 5.2 Write unit tests for error propagation and module interface
    - Test that network errors (e.g., `ConnectionError`) propagate unchanged (Req 5.2)
    - Test that `get_access_token`, `create_auth_client`, and `AuthenticationError` exist with correct signatures (Req 6.1, 6.2, 6.4)
    - Test that `GOVCLOUD_AUTHORITY_HOST` and `GOVCLOUD_GRAPH_SCOPE` have correct values (Req 7.1, 7.2, 7.4)
    - _Requirements: 5.2, 6.1, 6.2, 6.4, 7.1, 7.2, 7.4_

- [x] 6. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- The module is a single file (`sharepoint_auth.py`) — no package structure needed
- All tests go in `tests/test_sharepoint_auth.py` and mock MSAL — no real Azure AD calls
- Property tests use Hypothesis with a minimum of 100 iterations per property
- Test dependencies: `pytest`, `hypothesis`, `unittest.mock` (stdlib)
