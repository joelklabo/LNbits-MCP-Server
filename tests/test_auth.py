"""Tests for utils.auth module."""

from lnbits_mcp_server.utils.auth import AuthConfig, AuthMethod


class TestApiKeyHeader:
    def test_api_key_header(self):
        config = AuthConfig(api_key="test-key", auth_method=AuthMethod.API_KEY_HEADER)
        assert config.get_headers() == {"X-API-KEY": "test-key"}
        assert config.get_query_params() == {}


class TestApiKeyQuery:
    def test_api_key_query(self):
        config = AuthConfig(api_key="test-key", auth_method=AuthMethod.API_KEY_QUERY)
        assert config.get_query_params() == {"api_key": "test-key"}
        assert config.get_headers() == {}


class TestHttpBearer:
    def test_http_bearer(self):
        config = AuthConfig(
            bearer_token="my-bearer-token", auth_method=AuthMethod.HTTP_BEARER
        )
        assert config.get_headers() == {"Authorization": "Bearer my-bearer-token"}
        assert config.get_query_params() == {}


class TestOAuth2:
    def test_oauth2(self):
        config = AuthConfig(
            oauth2_token="my-oauth2-token", auth_method=AuthMethod.OAUTH2
        )
        assert config.get_headers() == {"Authorization": "Bearer my-oauth2-token"}
        assert config.get_query_params() == {}


class TestNoCredentials:
    def test_no_credentials(self):
        config = AuthConfig()
        assert config.get_headers() == {}
        assert config.get_query_params() == {}
        assert config.is_configured() is False


class TestIsConfigured:
    def test_is_configured_each_method(self):
        cases = [
            (AuthMethod.API_KEY_HEADER, {"api_key": "k"}),
            (AuthMethod.API_KEY_QUERY, {"api_key": "k"}),
            (AuthMethod.HTTP_BEARER, {"bearer_token": "t"}),
            (AuthMethod.OAUTH2, {"oauth2_token": "t"}),
        ]
        for method, kwargs in cases:
            config = AuthConfig(auth_method=method, **kwargs)
            assert config.is_configured() is True, f"Expected True for {method}"

    def test_is_configured_false_without_matching_credential(self):
        # api_key provided but method is HTTP_BEARER — should be False
        config = AuthConfig(api_key="k", auth_method=AuthMethod.HTTP_BEARER)
        assert config.is_configured() is False
