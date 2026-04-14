# Requirements Document

## Introduction

This spec covers Milestone 1 of the ImportDocuments Lambda C#-to-Python conversion: a standalone Python authentication module that acquires an OAuth2 access token from Azure AD GovCloud using the client credentials flow. The module replaces the internal `AI_Libraries.SharePoint` NuGet package's authentication behavior with direct use of the `msal` (Microsoft Authentication Library) Python package, targeting Azure AD GovCloud endpoints exclusively.

## Glossary

- **Auth_Module**: The Python module (`sharepoint_auth.py`) responsible for acquiring and returning an OAuth2 bearer token from Azure AD GovCloud.
- **MSAL_Client**: An instance of `msal.ConfidentialClientApplication` configured with GovCloud authority and client credentials.
- **Authority_URL**: The Azure AD GovCloud token endpoint base URL, formatted as `https://login.microsoftonline.us/{tenant_id}`.
- **Graph_Scope**: The Microsoft Graph GovCloud default scope string: `https://graph.microsoft.us/.default`.
- **Client_Credentials_Flow**: An OAuth2 grant type where the application authenticates using its own identity (client ID + client secret) rather than on behalf of a user.
- **Bearer_Token**: A string access token returned by Azure AD, used in the `Authorization` header of subsequent API requests.
- **Lambda_Invocation**: A single execution of the AWS Lambda function, from cold/warm start to completion.
- **Token_Cache**: The in-memory cache maintained by the MSAL_Client that stores acquired tokens for reuse within a single Lambda_Invocation.

## Requirements

### Requirement 1: MSAL Client Initialization with GovCloud Authority

**User Story:** As a developer integrating with Azure AD GovCloud, I want the Auth_Module to create an MSAL_Client configured with the correct GovCloud authority URL, so that token requests are directed to the GovCloud identity provider rather than the commercial Azure AD endpoint.

#### Acceptance Criteria

1. WHEN the Auth_Module is initialized with a tenant_id, THE Auth_Module SHALL construct the Authority_URL as `https://login.microsoftonline.us/{tenant_id}`.
2. WHEN the Auth_Module is initialized, THE MSAL_Client SHALL be created as a `ConfidentialClientApplication` using the provided client_id, client_secret, and the constructed Authority_URL.
3. THE Auth_Module SHALL use the GovCloud authority domain `login.microsoftonline.us` and SHALL NOT use the commercial domain `login.microsoftonline.com`.

### Requirement 2: Token Acquisition via Client Credentials Flow

**User Story:** As a downstream module (e.g., the SharePoint Graph API client), I want to call the Auth_Module and receive a valid Bearer_Token, so that I can authenticate requests to Microsoft Graph GovCloud.

#### Acceptance Criteria

1. WHEN a token is requested, THE Auth_Module SHALL first attempt to acquire a token silently from the Token_Cache using `acquire_token_silent_with_error`.
2. WHEN the Token_Cache does not contain a valid token, THE Auth_Module SHALL acquire a new token using `acquire_token_for_client` with the Graph_Scope `https://graph.microsoft.us/.default`.
3. WHEN token acquisition succeeds, THE Auth_Module SHALL return the `access_token` string from the MSAL response.
4. THE Auth_Module SHALL use the GovCloud Graph_Scope `https://graph.microsoft.us/.default` and SHALL NOT use the commercial scope `https://graph.microsoft.com/.default`.

### Requirement 3: Token Caching Within a Lambda Invocation

**User Story:** As a developer optimizing Lambda performance, I want the Auth_Module to reuse cached tokens within a single Lambda_Invocation, so that redundant network calls to Azure AD are avoided.

#### Acceptance Criteria

1. WHILE a Lambda_Invocation is in progress, THE MSAL_Client instance SHALL be reused across multiple token requests within that invocation.
2. WHEN a valid cached token exists in the Token_Cache, THE Auth_Module SHALL return the cached token without making a network call to Azure AD.
3. WHEN the cached token has expired, THE Auth_Module SHALL acquire a fresh token from Azure AD using the Client_Credentials_Flow.

### Requirement 4: Configuration from Environment Variables

**User Story:** As a DevOps engineer deploying the Lambda, I want the Auth_Module to read Azure AD credentials from environment variables, so that secrets are managed through the Lambda configuration and not hardcoded.

#### Acceptance Criteria

1. THE Auth_Module SHALL read the `tenantId` environment variable to obtain the Azure AD tenant identifier.
2. THE Auth_Module SHALL read the `clientId` environment variable to obtain the Azure AD application client identifier.
3. THE Auth_Module SHALL read the `clientSecret` environment variable to obtain the Azure AD application client secret.
4. IF the `tenantId` environment variable is missing or empty, THEN THE Auth_Module SHALL raise a `ValueError` with the message `Missing required environment variable: tenantId`.
5. IF the `clientId` environment variable is missing or empty, THEN THE Auth_Module SHALL raise a `ValueError` with the message `Missing required environment variable: clientId`.
6. IF the `clientSecret` environment variable is missing or empty, THEN THE Auth_Module SHALL raise a `ValueError` with the message `Missing required environment variable: clientSecret`.

### Requirement 5: Error Handling for Authentication Failures

**User Story:** As a developer troubleshooting Lambda failures, I want the Auth_Module to raise clear, specific exceptions for different authentication failure scenarios, so that I can quickly identify the root cause.

#### Acceptance Criteria

1. IF the MSAL token response contains an `error` field, THEN THE Auth_Module SHALL raise an `AuthenticationError` exception that includes the `error` and `error_description` values from the response.
2. IF a network error occurs during token acquisition, THEN THE Auth_Module SHALL propagate the underlying network exception without suppressing the original traceback.
3. IF the client_secret is expired or invalid, THEN THE Auth_Module SHALL raise an `AuthenticationError` with the error details returned by Azure AD.
4. IF the tenant_id does not correspond to a valid Azure AD tenant, THEN THE Auth_Module SHALL raise an `AuthenticationError` with the error details returned by Azure AD.

### Requirement 6: Module Interface

**User Story:** As a developer building the SharePoint Graph API client (Milestone 2), I want a simple, well-defined interface for obtaining a Bearer_Token, so that I can integrate authentication without understanding MSAL internals.

#### Acceptance Criteria

1. THE Auth_Module SHALL expose a function `get_access_token()` that returns a Bearer_Token string.
2. THE Auth_Module SHALL expose a function `create_auth_client(tenant_id, client_id, client_secret)` that returns an initialized MSAL_Client instance.
3. WHEN `get_access_token()` is called without prior initialization, THE Auth_Module SHALL read credentials from environment variables and initialize the MSAL_Client automatically.
4. THE Auth_Module SHALL define an `AuthenticationError` exception class that extends the built-in `Exception` class.

### Requirement 7: GovCloud Endpoint Enforcement

**User Story:** As a security engineer, I want to ensure the Auth_Module only communicates with GovCloud endpoints, so that authentication traffic never routes to commercial Azure AD infrastructure.

#### Acceptance Criteria

1. THE Auth_Module SHALL hardcode the authority domain as `login.microsoftonline.us`.
2. THE Auth_Module SHALL hardcode the Graph_Scope prefix as `https://graph.microsoft.us/`.
3. THE Auth_Module SHALL NOT accept or construct URLs containing `login.microsoftonline.com` or `graph.microsoft.com`.
4. THE Auth_Module SHALL define the GovCloud authority domain and Graph_Scope as module-level constants.

### Requirement 8: Python Runtime Compatibility

**User Story:** As a DevOps engineer, I want the Auth_Module to run on Python 3.12 in the AWS Lambda environment, so that it is compatible with the target deployment runtime.

#### Acceptance Criteria

1. THE Auth_Module SHALL be compatible with Python 3.12.
2. THE Auth_Module SHALL depend only on the `msal` library for Azure AD authentication (no other third-party authentication libraries).
3. THE Auth_Module SHALL use only standard library modules beyond the `msal` dependency.
