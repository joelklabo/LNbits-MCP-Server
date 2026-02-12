"""Runtime configuration manager for LNbits MCP server."""

import asyncio
import logging
from contextlib import asynccontextmanager
from threading import RLock
from typing import Any, Callable, Dict, Optional

from pydantic import HttpUrl, ValidationError

from ..client import LNbitsClient, LNbitsConfig
from ..utils.auth import AuthMethod

logger = logging.getLogger(__name__)


class RuntimeConfigManager:
    """Manages runtime configuration for the LNbits MCP server."""

    def __init__(self, initial_config: Optional[LNbitsConfig] = None):
        self._config = initial_config or LNbitsConfig()
        self._client: Optional[LNbitsClient] = None
        self._lock = RLock()
        self._is_configured = False
        # Async callback invoked after configuration changes (e.g. re-discover tools)
        self.on_config_changed: Optional[Any] = None

    @property
    def config(self) -> LNbitsConfig:
        """Get current configuration."""
        with self._lock:
            return self._config

    @property
    def is_configured(self) -> bool:
        """Check if configuration has been set through runtime tools."""
        with self._lock:
            return self._is_configured

    async def get_client(self) -> LNbitsClient:
        """Get the current LNbits client, creating one if necessary."""
        with self._lock:
            if not self._client:
                self._client = LNbitsClient(self._config)
            return self._client

    async def update_configuration(
        self,
        lnbits_url: Optional[str] = None,
        api_key: Optional[str] = None,
        bearer_token: Optional[str] = None,
        oauth2_token: Optional[str] = None,
        auth_method: Optional[str] = None,
        timeout: Optional[int] = None,
        rate_limit_per_minute: Optional[int] = None,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update the runtime configuration.

        Args:
            lnbits_url: Base URL for LNbits instance
            api_key: API key for authentication
            bearer_token: Bearer token for authentication
            oauth2_token: OAuth2 token for authentication
            auth_method: Authentication method to use
            timeout: Request timeout in seconds
            rate_limit_per_minute: Rate limit per minute

        Returns:
            Dictionary with update results

        Raises:
            ValidationError: If configuration is invalid
        """
        with self._lock:
            original_config = self._config.model_copy()
            try:
                config_dict = self._config.model_dump()
                if lnbits_url is not None:
                    config_dict["lnbits_url"] = lnbits_url
                if api_key is not None:
                    config_dict["api_key"] = api_key
                if bearer_token is not None:
                    config_dict["bearer_token"] = bearer_token
                if oauth2_token is not None:
                    config_dict["oauth2_token"] = oauth2_token
                if auth_method is not None:
                    config_dict["auth_method"] = auth_method
                if timeout is not None:
                    config_dict["timeout"] = timeout
                if rate_limit_per_minute is not None:
                    config_dict["rate_limit_per_minute"] = rate_limit_per_minute
                if access_token is not None:
                    config_dict["access_token"] = access_token

                new_config = LNbitsConfig(**config_dict)

                if self._client:
                    if hasattr(self._client, "close"):
                        await self._client.close()
                    self._client = None

                self._config = new_config
                self._is_configured = True
                logger.info(
                    f"Configuration updated successfully: {new_config.lnbits_url}"
                )

                result = {
                    "success": True,
                    "message": "Configuration updated successfully",
                    "config": self._get_safe_config_dict(),
                }
            except ValidationError as e:
                self._config = original_config
                logger.error(f"Configuration validation failed: {e}")
                raise
            except Exception as e:
                self._config = original_config
                logger.error(f"Configuration update failed: {e}")
                raise

        # Fire callback outside the lock
        if self.on_config_changed is not None:
            try:
                await self.on_config_changed()
            except Exception as exc:
                logger.warning(f"on_config_changed callback failed: {exc}")

        return result

    async def test_configuration(self) -> Dict[str, Any]:
        """Test the current configuration by making a test API call.

        Returns:
            Dictionary with test results
        """
        try:
            client = await self.get_client()
            wallet_info = await client.get("/api/v1/wallet")
            return {
                "success": True,
                "message": "Configuration test successful",
                "wallet_info": {
                    "id": wallet_info.get("id", "N/A"),
                    "name": wallet_info.get("name", "N/A"),
                    "balance": wallet_info.get("balance", 0),
                },
            }

        except Exception as e:
            logger.error(f"Configuration test failed: {e}")
            error_message = str(e)

            # Provide better error messages for common issues
            if "404" in error_message and "Wallet not found" in error_message:
                error_message = (
                    "The API key provided is not valid or the wallet doesn't exist. "
                    "Please check:\n\n"
                    "1. Go to your LNbits instance web interface\n"
                    "2. Create a new wallet or access an existing one\n"
                    "3. Click on the wallet name to access it\n"
                    "4. Look for 'API Info' or 'API Keys' section\n"
                    "5. Copy the 'Invoice/read key' or 'Admin key' (depending on what you need)\n"
                    "6. Make sure the API key is from the correct wallet\n\n"
                    "If using demo.lnbits.com, you need to create a wallet first by visiting the website."
                )

            return {
                "success": False,
                "message": f"Configuration test failed: {error_message}",
                "error": str(e),
            }

    def get_configuration_status(self) -> Dict[str, Any]:
        """Get the current configuration status.

        Returns:
            Dictionary with configuration status
        """
        with self._lock:
            return {
                "is_configured": self._is_configured,
                "config": self._get_safe_config_dict(),
            }

    def _get_safe_config_dict(self) -> Dict[str, Any]:
        """Get configuration dictionary with sensitive data masked."""
        config_dict = self._config.model_dump()

        # Convert HttpUrl to string for JSON serialization
        if "lnbits_url" in config_dict:
            config_dict["lnbits_url"] = str(config_dict["lnbits_url"])

        # Mask sensitive fields
        if config_dict.get("api_key"):
            config_dict["api_key"] = "***MASKED***"
        if config_dict.get("bearer_token"):
            config_dict["bearer_token"] = "***MASKED***"
        if config_dict.get("oauth2_token"):
            config_dict["oauth2_token"] = "***MASKED***"
        if config_dict.get("access_token"):
            config_dict["access_token"] = "***MASKED***"

        return config_dict

    async def close(self):
        """Close the configuration manager and cleanup resources."""
        with self._lock:
            if self._client:
                if hasattr(self._client, "close"):
                    await self._client.close()
                self._client = None

    @asynccontextmanager
    async def get_client_context(self):
        """Context manager for getting a client with proper cleanup."""
        client = await self.get_client()
        try:
            yield client
        finally:
            # Client will be reused, so we don't close it here
            pass
