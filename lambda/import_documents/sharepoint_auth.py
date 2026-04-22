"""SharePoint authentication module for Azure AD GovCloud.

Acquires OAuth2 access tokens from Azure AD GovCloud using the MSAL
client credentials flow. All endpoints are hardcoded to GovCloud —
no commercial Azure AD support.
"""

import os

import boto3
import msal

# GovCloud-only endpoint constants (Req 7.1, 7.2, 7.4)
GOVCLOUD_AUTHORITY_HOST: str = "login.microsoftonline.us"
GOVCLOUD_GRAPH_SCOPE: list[str] = ["https://graph.microsoft.us/.default"]

# Module-level singleton — initialized on first get_access_token() call (Req 3.1)
_client: msal.ConfidentialClientApplication | None = None


class AuthenticationError(Exception):
    """Raised when Azure AD token acquisition fails."""

    def __init__(self, error: str, error_description: str = ""):
        self.error = error
        self.error_description = error_description
        super().__init__(f"{error}: {error_description}")


def create_auth_client(
    tenant_id: str,
    client_id: str,
    client_secret: str,
) -> msal.ConfidentialClientApplication:
    """Create a configured MSAL ConfidentialClientApplication for GovCloud.

    Constructs the GovCloud authority URL and returns an MSAL client
    ready for token acquisition. No network calls are made during creation.

    Args:
        tenant_id: Azure AD GovCloud tenant identifier.
        client_id: Azure AD application (client) identifier.
        client_secret: Azure AD application client secret.

    Returns:
        A configured ConfidentialClientApplication instance.
    """
    authority = f"https://{GOVCLOUD_AUTHORITY_HOST}/{tenant_id}"
    return msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )


def get_access_token() -> str:
    """Acquire a bearer token from Azure AD GovCloud.

    On first call, reads credentials from environment variables, validates
    them, and initializes the module-level MSAL client. Subsequent calls
    reuse the existing client (singleton pattern).

    Uses a two-step cache-first pattern:
    1. Attempt silent token acquisition from the MSAL cache
    2. On cache miss, acquire a fresh token via client credentials flow

    Returns:
        The access token string.

    Raises:
        ValueError: If a required environment variable is missing or empty.
        AuthenticationError: If Azure AD returns an error response.
    """
    global _client

    if _client is None:
        # Read and validate required environment variables (Req 4.1–4.6)
        for name in ("tenantId", "clientId"):
            value = os.environ.get(name, "")
            if not value:
                raise ValueError(f"Missing required environment variable: {name}")

        tenant_id = os.environ["tenantId"]
        client_id = os.environ["clientId"]

        # Resolve client secret: prefer direct env var, fall back to Secrets Manager
        client_secret = os.environ.get("clientSecret", "")
        if not client_secret:
            client_secret_arn = os.environ.get("clientSecretArn", "")
            if not client_secret_arn:
                raise ValueError(
                    "Missing required environment variable: either clientSecret "
                    "or clientSecretArn must be set"
                )
            sm = boto3.client("secretsmanager")
            resp = sm.get_secret_value(SecretId=client_secret_arn)
            client_secret = resp["SecretString"]

        _client = create_auth_client(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )

    # Step 1: Try the cache first (Req 2.1, 3.2)
    result = _client.acquire_token_silent_with_error(
        GOVCLOUD_GRAPH_SCOPE, account=None
    )

    # If silent returned an error dict, raise immediately
    if result is not None and "error" in result:
        raise AuthenticationError(
            error=result["error"],
            error_description=result.get("error_description", ""),
        )

    # Step 2: Cache miss — acquire fresh token (Req 2.2)
    if result is None:
        result = _client.acquire_token_for_client(scopes=GOVCLOUD_GRAPH_SCOPE)

    # Return token or raise on error (Req 2.3, 5.1)
    if "access_token" in result:
        return result["access_token"]

    raise AuthenticationError(
        error=result["error"],
        error_description=result.get("error_description", ""),
    )
