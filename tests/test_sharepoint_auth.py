"""Property-based tests for sharepoint_auth module.

All tests mock MSAL — no real Azure AD calls are made.
"""

from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, strategies as st

import os

import sharepoint_auth
from sharepoint_auth import (
    AuthenticationError,
    create_auth_client,
    get_access_token,
    GOVCLOUD_AUTHORITY_HOST,
    GOVCLOUD_GRAPH_SCOPE,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty text strings for credential fields
_credential_text = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())

# Adversarial tenant IDs that may contain commercial domain substrings
_adversarial_tenant_id = st.one_of(
    _credential_text,
    st.just("login.microsoftonline.com"),
    st.just("graph.microsoft.com"),
    st.just("tenant-login.microsoftonline.com-suffix"),
    st.text(min_size=1, max_size=100).map(
        lambda s: f"{s}login.microsoftonline.com{s}"
    ),
)


# ---------------------------------------------------------------------------
# Property 1: Auth client configuration preserves credentials and uses
#              GovCloud authority
# Feature: sharepoint-auth-module, Property 1: Auth client configuration
#          preserves credentials and uses GovCloud authority
# Validates: Requirements 1.1, 1.2
# ---------------------------------------------------------------------------


class TestProperty1AuthClientConfiguration:
    """Feature: sharepoint-auth-module, Property 1: Auth client configuration preserves credentials and uses GovCloud authority"""

    @given(
        tenant_id=_credential_text,
        client_id=_credential_text,
        client_secret=_credential_text,
    )
    @settings(max_examples=100)
    def test_auth_client_preserves_credentials_and_govcloud_authority(
        self, tenant_id, client_id, client_secret
    ):
        """**Validates: Requirements 1.1, 1.2**

        For any valid (tenant_id, client_id, client_secret) tuple,
        create_auth_client SHALL produce a ConfidentialClientApplication
        whose authority URL equals https://login.microsoftonline.us/{tenant_id}
        and whose credentials match the provided values.
        """
        with patch("sharepoint_auth.msal.ConfidentialClientApplication") as mock_cca:
            mock_instance = MagicMock()
            mock_cca.return_value = mock_instance

            result = create_auth_client(tenant_id, client_id, client_secret)

            # Verify the constructor was called exactly once
            mock_cca.assert_called_once()

            call_kwargs = mock_cca.call_args
            expected_authority = f"https://{GOVCLOUD_AUTHORITY_HOST}/{tenant_id}"

            # Authority URL must be GovCloud with the given tenant_id
            assert call_kwargs.kwargs["authority"] == expected_authority, (
                f"Expected authority {expected_authority}, "
                f"got {call_kwargs.kwargs['authority']}"
            )

            # client_id must match
            assert call_kwargs.kwargs["client_id"] == client_id

            # client_credential must match
            assert call_kwargs.kwargs["client_credential"] == client_secret

            # Return value must be the MSAL instance
            assert result is mock_instance


# ---------------------------------------------------------------------------
# Property 4: GovCloud-only endpoint enforcement
# Feature: sharepoint-auth-module, Property 4: GovCloud-only endpoint
#          enforcement
# Validates: Requirements 1.3, 2.4, 7.1, 7.2, 7.3
# ---------------------------------------------------------------------------


class TestProperty4GovCloudOnlyEndpointEnforcement:
    """Feature: sharepoint-auth-module, Property 4: GovCloud-only endpoint enforcement"""

    @given(tenant_id=_adversarial_tenant_id)
    @settings(max_examples=100)
    def test_authority_url_never_contains_commercial_domains(self, tenant_id):
        """**Validates: Requirements 1.3, 2.4, 7.1, 7.2, 7.3**

        For any tenant_id string (including adversarial ones containing
        commercial domain substrings), the authority URL constructed by
        create_auth_client SHALL NOT contain 'login.microsoftonline.com'
        or 'graph.microsoft.com', and GOVCLOUD_GRAPH_SCOPE SHALL NOT
        contain any scope string with 'graph.microsoft.com'.
        """
        with patch("sharepoint_auth.msal.ConfidentialClientApplication") as mock_cca:
            mock_cca.return_value = MagicMock()

            create_auth_client(tenant_id, "any-client-id", "any-secret")

            call_kwargs = mock_cca.call_args
            authority_url = call_kwargs.kwargs["authority"]

            # The authority HOST portion must be GovCloud — the tenant_id
            # is a path segment and doesn't affect the host.
            # We verify the authority starts with the GovCloud prefix.
            expected_prefix = f"https://{GOVCLOUD_AUTHORITY_HOST}/"
            assert authority_url.startswith(expected_prefix), (
                f"Authority URL must start with {expected_prefix}, "
                f"got {authority_url}"
            )

            # The host portion (between https:// and the first / after it)
            # must never be the commercial domain
            host = authority_url.split("//")[1].split("/")[0]
            assert host != "login.microsoftonline.com", (
                "Authority host must not be the commercial domain"
            )
            assert "graph.microsoft.com" not in authority_url.split("/")[2], (
                "Authority host must not contain graph.microsoft.com"
            )

        # GOVCLOUD_GRAPH_SCOPE must not contain commercial domain strings
        for scope in GOVCLOUD_GRAPH_SCOPE:
            assert "graph.microsoft.com" not in scope, (
                f"GOVCLOUD_GRAPH_SCOPE contains commercial domain: {scope}"
            )
            assert "login.microsoftonline.com" not in scope, (
                f"GOVCLOUD_GRAPH_SCOPE contains commercial domain: {scope}"
            )


# ---------------------------------------------------------------------------
# Strategy: Non-empty access token strings
# ---------------------------------------------------------------------------

_access_token_text = st.text(min_size=1, max_size=500).filter(lambda s: s.strip())

# Non-empty error/error_description string pairs
_error_text = st.text(min_size=1, max_size=300).filter(lambda s: s.strip())

# Valid env var values (non-empty strings, no null bytes or surrogates — os.environ rejects them)
_env_value = st.text(
    alphabet=st.characters(
        blacklist_characters="\x00",
        blacklist_categories=("Cs",),  # exclude surrogates
    ),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip())


# ---------------------------------------------------------------------------
# Property 2: Successful token extraction
# Feature: sharepoint-auth-module, Property 2: Successful token extraction
# Validates: Requirements 2.3
# ---------------------------------------------------------------------------


class TestProperty2SuccessfulTokenExtraction:
    """Feature: sharepoint-auth-module, Property 2: Successful token extraction"""

    @given(access_token=_access_token_text)
    @settings(max_examples=100)
    def test_get_access_token_returns_exact_token_string(self, access_token):
        """**Validates: Requirements 2.3**

        For any MSAL response dict containing an access_token key with a
        non-empty string value, get_access_token() SHALL return that exact
        string unchanged.
        """
        # Reset the module-level singleton to ensure clean state
        sharepoint_auth._client = None

        env = {
            "tenantId": "test-tenant",
            "clientId": "test-client",
            "clientSecret": "test-secret",
        }

        with patch.dict(os.environ, env, clear=False), \
             patch("sharepoint_auth.msal.ConfidentialClientApplication") as mock_cca:
            mock_instance = MagicMock()
            mock_cca.return_value = mock_instance

            # Silent returns None (cache miss), acquire_token_for_client returns success
            mock_instance.acquire_token_silent_with_error.return_value = None
            mock_instance.acquire_token_for_client.return_value = {
                "access_token": access_token,
                "token_type": "Bearer",
            }

            result = get_access_token()

            assert result == access_token, (
                f"Expected exact token '{access_token}', got '{result}'"
            )


# ---------------------------------------------------------------------------
# Property 3: Error response raises AuthenticationError with matching fields
# Feature: sharepoint-auth-module, Property 3: Error response raises
#          AuthenticationError with matching fields
# Validates: Requirements 5.1, 5.3, 5.4
# ---------------------------------------------------------------------------


class TestProperty3ErrorResponseRaisesAuthenticationError:
    """Feature: sharepoint-auth-module, Property 3: Error response raises AuthenticationError with matching fields"""

    @given(error=_error_text, error_description=_error_text)
    @settings(max_examples=100)
    def test_error_response_raises_authentication_error_with_matching_fields(
        self, error, error_description
    ):
        """**Validates: Requirements 5.1, 5.3, 5.4**

        For any MSAL response dict containing an error key and an
        error_description key, get_access_token() SHALL raise an
        AuthenticationError whose error attribute equals the response's
        error value and whose error_description attribute equals the
        response's error_description value.
        """
        # Reset the module-level singleton to ensure clean state
        sharepoint_auth._client = None

        env = {
            "tenantId": "test-tenant",
            "clientId": "test-client",
            "clientSecret": "test-secret",
        }

        with patch.dict(os.environ, env, clear=False), \
             patch("sharepoint_auth.msal.ConfidentialClientApplication") as mock_cca:
            mock_instance = MagicMock()
            mock_cca.return_value = mock_instance

            # Silent returns None (cache miss), acquire_token_for_client returns error
            mock_instance.acquire_token_silent_with_error.return_value = None
            mock_instance.acquire_token_for_client.return_value = {
                "error": error,
                "error_description": error_description,
            }

            with pytest.raises(AuthenticationError) as exc_info:
                get_access_token()

            assert exc_info.value.error == error, (
                f"Expected error '{error}', got '{exc_info.value.error}'"
            )
            assert exc_info.value.error_description == error_description, (
                f"Expected error_description '{error_description}', "
                f"got '{exc_info.value.error_description}'"
            )


# ---------------------------------------------------------------------------
# Property 5: Missing environment variable validation
# Feature: sharepoint-auth-module, Property 5: Missing environment variable
#          validation
# Validates: Requirements 4.4, 4.5, 4.6
# ---------------------------------------------------------------------------


class TestProperty5MissingEnvironmentVariableValidation:
    """Feature: sharepoint-auth-module, Property 5: Missing environment variable validation"""

    @given(
        client_id_val=_env_value,
        client_secret_val=_env_value,
    )
    @settings(max_examples=100)
    def test_missing_tenant_id_raises_value_error(
        self, client_id_val, client_secret_val
    ):
        """**Validates: Requirements 4.4**

        If tenantId is missing or empty, get_access_token() SHALL raise
        a ValueError whose message contains 'tenantId'.
        """
        sharepoint_auth._client = None

        # tenantId is absent from the environment
        env = {
            "clientId": client_id_val,
            "clientSecret": client_secret_val,
        }

        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="tenantId"):
                get_access_token()

    @given(
        tenant_id_val=_env_value,
        client_secret_val=_env_value,
    )
    @settings(max_examples=100)
    def test_missing_client_id_raises_value_error(
        self, tenant_id_val, client_secret_val
    ):
        """**Validates: Requirements 4.5**

        If clientId is missing or empty, get_access_token() SHALL raise
        a ValueError whose message contains 'clientId'.
        """
        sharepoint_auth._client = None

        # clientId is absent from the environment
        env = {
            "tenantId": tenant_id_val,
            "clientSecret": client_secret_val,
        }

        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="clientId"):
                get_access_token()

    @given(
        tenant_id_val=_env_value,
        client_id_val=_env_value,
    )
    @settings(max_examples=100)
    def test_missing_client_secret_raises_value_error(
        self, tenant_id_val, client_id_val
    ):
        """**Validates: Requirements 4.6**

        If clientSecret is missing or empty, get_access_token() SHALL raise
        a ValueError whose message contains 'clientSecret'.
        """
        sharepoint_auth._client = None

        # clientSecret is absent from the environment
        env = {
            "tenantId": tenant_id_val,
            "clientId": client_id_val,
        }

        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="clientSecret"):
                get_access_token()

    @given(
        client_id_val=_env_value,
        client_secret_val=_env_value,
    )
    @settings(max_examples=100)
    def test_empty_tenant_id_raises_value_error(
        self, client_id_val, client_secret_val
    ):
        """**Validates: Requirements 4.4**

        If tenantId is set to an empty string, get_access_token() SHALL
        raise a ValueError whose message contains 'tenantId'.
        """
        sharepoint_auth._client = None

        env = {
            "tenantId": "",
            "clientId": client_id_val,
            "clientSecret": client_secret_val,
        }

        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="tenantId"):
                get_access_token()

    @given(
        tenant_id_val=_env_value,
        client_secret_val=_env_value,
    )
    @settings(max_examples=100)
    def test_empty_client_id_raises_value_error(
        self, tenant_id_val, client_secret_val
    ):
        """**Validates: Requirements 4.5**

        If clientId is set to an empty string, get_access_token() SHALL
        raise a ValueError whose message contains 'clientId'.
        """
        sharepoint_auth._client = None

        env = {
            "tenantId": tenant_id_val,
            "clientId": "",
            "clientSecret": client_secret_val,
        }

        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="clientId"):
                get_access_token()

    @given(
        tenant_id_val=_env_value,
        client_id_val=_env_value,
    )
    @settings(max_examples=100)
    def test_empty_client_secret_raises_value_error(
        self, tenant_id_val, client_id_val
    ):
        """**Validates: Requirements 4.6**

        If clientSecret is set to an empty string, get_access_token() SHALL
        raise a ValueError whose message contains 'clientSecret'.
        """
        sharepoint_auth._client = None

        env = {
            "tenantId": tenant_id_val,
            "clientId": client_id_val,
            "clientSecret": "",
        }

        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="clientSecret"):
                get_access_token()


# ===========================================================================
# Task 5.1: Unit tests for cache-first behavior and singleton pattern
# ===========================================================================

_VALID_ENV = {
    "tenantId": "test-tenant-id",
    "clientId": "test-client-id",
    "clientSecret": "test-client-secret",
}


class TestCacheFirstBehaviorAndSingleton:
    """Unit tests for cache-first token acquisition and singleton client reuse."""

    def test_silent_called_before_acquire_for_client(self):
        """Req 2.1: acquire_token_silent_with_error is called before acquire_token_for_client."""
        sharepoint_auth._client = None
        call_order = []

        with patch.dict(os.environ, _VALID_ENV, clear=False), \
             patch("sharepoint_auth.msal.ConfidentialClientApplication") as mock_cca:
            mock_instance = MagicMock()
            mock_cca.return_value = mock_instance

            mock_instance.acquire_token_silent_with_error.side_effect = (
                lambda *a, **kw: (call_order.append("silent"), None)[-1]
            )
            mock_instance.acquire_token_for_client.side_effect = (
                lambda *a, **kw: (
                    call_order.append("for_client"),
                    {"access_token": "tok"},
                )[-1]
            )

            get_access_token()

        assert call_order == ["silent", "for_client"], (
            f"Expected silent before for_client, got {call_order}"
        )

    def test_cache_hit_skips_acquire_for_client(self):
        """Req 3.2: When cache returns a valid token, acquire_token_for_client is NOT called."""
        sharepoint_auth._client = None

        with patch.dict(os.environ, _VALID_ENV, clear=False), \
             patch("sharepoint_auth.msal.ConfidentialClientApplication") as mock_cca:
            mock_instance = MagicMock()
            mock_cca.return_value = mock_instance

            # Silent returns a cached token
            mock_instance.acquire_token_silent_with_error.return_value = {
                "access_token": "cached-token",
            }

            result = get_access_token()

            assert result == "cached-token"
            mock_instance.acquire_token_for_client.assert_not_called()

    def test_client_reused_across_multiple_calls(self):
        """Req 3.1: _client is reused (same object) across multiple get_access_token() calls."""
        sharepoint_auth._client = None

        with patch.dict(os.environ, _VALID_ENV, clear=False), \
             patch("sharepoint_auth.msal.ConfidentialClientApplication") as mock_cca:
            mock_instance = MagicMock()
            mock_cca.return_value = mock_instance

            mock_instance.acquire_token_silent_with_error.return_value = None
            mock_instance.acquire_token_for_client.return_value = {
                "access_token": "tok",
            }

            get_access_token()
            client_after_first = sharepoint_auth._client

            get_access_token()
            client_after_second = sharepoint_auth._client

            assert client_after_first is client_after_second
            # ConfidentialClientApplication constructor called only once
            mock_cca.assert_called_once()

    def test_auto_initialization_from_env_vars(self):
        """Req 6.3: When _client is None, get_access_token() reads env vars and initializes."""
        sharepoint_auth._client = None

        with patch.dict(os.environ, _VALID_ENV, clear=False), \
             patch("sharepoint_auth.msal.ConfidentialClientApplication") as mock_cca:
            mock_instance = MagicMock()
            mock_cca.return_value = mock_instance

            mock_instance.acquire_token_silent_with_error.return_value = None
            mock_instance.acquire_token_for_client.return_value = {
                "access_token": "tok",
            }

            assert sharepoint_auth._client is None
            get_access_token()
            assert sharepoint_auth._client is not None

            # Verify the client was created with the env var values
            call_kwargs = mock_cca.call_args.kwargs
            assert call_kwargs["client_id"] == "test-client-id"
            assert call_kwargs["client_credential"] == "test-client-secret"
            assert "test-tenant-id" in call_kwargs["authority"]


# ===========================================================================
# Task 5.2: Unit tests for error propagation and module interface
# ===========================================================================

import inspect


class TestErrorPropagationAndModuleInterface:
    """Unit tests for network error propagation, module interface, and GovCloud constants."""

    def test_network_error_propagates_unchanged(self):
        """Req 5.2: Network errors (e.g., ConnectionError) propagate without wrapping."""
        sharepoint_auth._client = None

        with patch.dict(os.environ, _VALID_ENV, clear=False), \
             patch("sharepoint_auth.msal.ConfidentialClientApplication") as mock_cca:
            mock_instance = MagicMock()
            mock_cca.return_value = mock_instance

            mock_instance.acquire_token_silent_with_error.side_effect = ConnectionError(
                "network down"
            )

            with pytest.raises(ConnectionError, match="network down"):
                get_access_token()

    def test_get_access_token_exists_with_correct_signature(self):
        """Req 6.1: get_access_token() exists and takes no parameters."""
        assert callable(get_access_token)
        sig = inspect.signature(get_access_token)
        assert len(sig.parameters) == 0, (
            f"get_access_token should take no parameters, has {list(sig.parameters)}"
        )

    def test_create_auth_client_exists_with_correct_signature(self):
        """Req 6.2: create_auth_client(tenant_id, client_id, client_secret) exists."""
        assert callable(create_auth_client)
        sig = inspect.signature(create_auth_client)
        param_names = list(sig.parameters.keys())
        assert param_names == ["tenant_id", "client_id", "client_secret"], (
            f"Expected params [tenant_id, client_id, client_secret], got {param_names}"
        )

    def test_authentication_error_exists_and_extends_exception(self):
        """Req 6.4: AuthenticationError is defined and extends Exception."""
        assert issubclass(AuthenticationError, Exception)
        err = AuthenticationError("code", "desc")
        assert err.error == "code"
        assert err.error_description == "desc"

    def test_govcloud_authority_host_value(self):
        """Req 7.1: GOVCLOUD_AUTHORITY_HOST equals 'login.microsoftonline.us'."""
        assert GOVCLOUD_AUTHORITY_HOST == "login.microsoftonline.us"

    def test_govcloud_graph_scope_value(self):
        """Req 7.2, 7.4: GOVCLOUD_GRAPH_SCOPE is a list with the correct GovCloud scope."""
        assert isinstance(GOVCLOUD_GRAPH_SCOPE, list)
        assert GOVCLOUD_GRAPH_SCOPE == ["https://graph.microsoft.us/.default"]


# ===========================================================================
# Task 9.1: Tests for Secrets Manager integration (clientSecretArn code path)
# ===========================================================================


class TestSecretsManagerIntegration:
    """Tests for the Secrets Manager retrieval path introduced by Task 8.

    Validates: Requirements 3.2, 4.2, 5.5
    """

    def test_secrets_manager_path_retrieves_secret(self):
        """When only clientSecretArn is set (no clientSecret), boto3 secretsmanager
        client is called with the correct ARN and the retrieved secret is passed
        to create_auth_client.

        Validates: Requirements 3.2, 4.2
        """
        sharepoint_auth._client = None

        env = {
            "tenantId": "test-tenant",
            "clientId": "test-client",
            "clientSecretArn": "arn:aws-us-gov:secretsmanager:us-gov-west-1:123456789012:secret:my-secret",
        }

        with patch.dict(os.environ, env, clear=True), \
             patch("sharepoint_auth.boto3.client") as mock_boto_client, \
             patch("sharepoint_auth.msal.ConfidentialClientApplication") as mock_cca:

            # Set up the Secrets Manager mock
            mock_sm = MagicMock()
            mock_boto_client.return_value = mock_sm
            mock_sm.get_secret_value.return_value = {
                "SecretString": "retrieved-secret-value",
            }

            # Set up the MSAL mock
            mock_instance = MagicMock()
            mock_cca.return_value = mock_instance
            mock_instance.acquire_token_silent_with_error.return_value = None
            mock_instance.acquire_token_for_client.return_value = {
                "access_token": "tok",
            }

            get_access_token()

            # Verify boto3 was called to create a secretsmanager client
            mock_boto_client.assert_called_once_with("secretsmanager")

            # Verify GetSecretValue was called with the correct ARN
            mock_sm.get_secret_value.assert_called_once_with(
                SecretId="arn:aws-us-gov:secretsmanager:us-gov-west-1:123456789012:secret:my-secret"
            )

            # Verify the retrieved secret was passed to create_auth_client
            call_kwargs = mock_cca.call_args.kwargs
            assert call_kwargs["client_credential"] == "retrieved-secret-value"

    def test_client_secret_env_var_takes_precedence(self):
        """When both clientSecret and clientSecretArn are set, clientSecret is
        used directly and boto3 is NOT called.

        Validates: Requirements 3.2, 5.5
        """
        sharepoint_auth._client = None

        env = {
            "tenantId": "test-tenant",
            "clientId": "test-client",
            "clientSecret": "direct-secret",
            "clientSecretArn": "arn:aws-us-gov:secretsmanager:us-gov-west-1:123456789012:secret:my-secret",
        }

        with patch.dict(os.environ, env, clear=True), \
             patch("sharepoint_auth.boto3.client") as mock_boto_client, \
             patch("sharepoint_auth.msal.ConfidentialClientApplication") as mock_cca:

            mock_instance = MagicMock()
            mock_cca.return_value = mock_instance
            mock_instance.acquire_token_silent_with_error.return_value = None
            mock_instance.acquire_token_for_client.return_value = {
                "access_token": "tok",
            }

            get_access_token()

            # boto3 should NOT have been called — clientSecret env var takes precedence
            mock_boto_client.assert_not_called()

            # Verify the direct secret was used
            call_kwargs = mock_cca.call_args.kwargs
            assert call_kwargs["client_credential"] == "direct-secret"

    def test_secrets_manager_error_propagates(self):
        """When clientSecretArn is set but the boto3 call raises an exception,
        the exception propagates to the caller.

        Validates: Requirements 5.5
        """
        from botocore.exceptions import ClientError

        sharepoint_auth._client = None

        env = {
            "tenantId": "test-tenant",
            "clientId": "test-client",
            "clientSecretArn": "arn:aws-us-gov:secretsmanager:us-gov-west-1:123456789012:secret:bad-secret",
        }

        with patch.dict(os.environ, env, clear=True), \
             patch("sharepoint_auth.boto3.client") as mock_boto_client:

            mock_sm = MagicMock()
            mock_boto_client.return_value = mock_sm
            mock_sm.get_secret_value.side_effect = ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": "Secret not found"}},
                "GetSecretValue",
            )

            with pytest.raises(ClientError):
                get_access_token()

    def test_neither_secret_nor_arn_raises_value_error(self):
        """When neither clientSecret nor clientSecretArn is set, ValueError is raised.

        Validates: Requirements 5.5
        """
        sharepoint_auth._client = None

        env = {
            "tenantId": "test-tenant",
            "clientId": "test-client",
        }

        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="clientSecret"):
                get_access_token()
