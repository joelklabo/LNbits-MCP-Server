"""LNbits API client for MCP server."""

import asyncio
import re
from typing import Any, Dict, Optional

import httpx
import structlog

from .utils.auth import AuthConfig, AuthMethod

logger = structlog.get_logger(__name__)


# -- Re-export config/error so existing imports keep working --

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings


class LNbitsConfig(BaseSettings):
    """Configuration for LNbits client."""

    lnbits_url: HttpUrl = Field(
        default="https://demo.lnbits.com",
        description="Base URL for LNbits instance",
    )
    api_key: Optional[str] = Field(
        default=None, description="API key for LNbits authentication"
    )
    bearer_token: Optional[str] = Field(
        default=None, description="Bearer token for authentication"
    )
    oauth2_token: Optional[str] = Field(
        default=None, description="OAuth2 token for authentication"
    )
    auth_method: AuthMethod = Field(
        default=AuthMethod.API_KEY_HEADER, description="Authentication method to use"
    )
    timeout: int = Field(default=30, description="Request timeout in seconds")
    max_retries: int = Field(
        default=3, description="Maximum number of retries for failed requests"
    )
    rate_limit_per_minute: int = Field(default=60, description="Rate limit per minute")

    model_config = {"env_prefix": "LNBITS_", "case_sensitive": False}


class LNbitsError(Exception):
    """Base exception for LNbits API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class LNbitsClient:
    """Asynchronous client for LNbits API."""

    def __init__(self, config: Optional[LNbitsConfig] = None):
        self.config = config or LNbitsConfig()
        self.auth_config = AuthConfig(
            api_key=self.config.api_key,
            bearer_token=self.config.bearer_token,
            oauth2_token=self.config.oauth2_token,
            auth_method=self.config.auth_method,
        )
        self.client: Optional[httpx.AsyncClient] = None
        self._rate_limiter = asyncio.Semaphore(self.config.rate_limit_per_minute)

    async def __aenter__(self):
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def _ensure_client(self):
        if not self.client:
            self.client = httpx.AsyncClient(
                base_url=str(self.config.lnbits_url),
                timeout=self.config.timeout,
                headers=self.auth_config.get_headers(),
            )

    # ------------------------------------------------------------------
    # Core HTTP methods (used by the generic dispatcher)
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """Make an authenticated request to the LNbits API."""
        await self._ensure_client()

        if params is None:
            params = {}
        params.update(self.auth_config.get_query_params())

        async with self._rate_limiter:
            try:
                response = await self.client.request(
                    method=method, url=path, params=params, json=json, **kwargs
                )

                logger.info(
                    "API request",
                    method=method,
                    path=path,
                    status_code=response.status_code,
                )

                if response.status_code >= 400:
                    error_msg = f"API request failed: {response.status_code}"
                    try:
                        error_detail = response.json()
                        if "detail" in error_detail:
                            error_msg += f" - {error_detail['detail']}"
                    except Exception:
                        error_msg += f" - {response.text}"
                    raise LNbitsError(error_msg, response.status_code)

                return response.json()

            except httpx.RequestError as e:
                logger.error("Request error", error=str(e), path=path)
                raise LNbitsError(f"Request failed: {e}")

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self._request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> Any:
        return await self._request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return await self._request("DELETE", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> Any:
        return await self._request("PATCH", path, **kwargs)

    # ------------------------------------------------------------------
    # Lightning address (multi-step flow, kept as convenience method)
    # ------------------------------------------------------------------

    async def resolve_lightning_address(self, lightning_address: str) -> Optional[str]:
        """Resolve a Lightning address to an LNURL-pay callback URL."""
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", lightning_address):
            raise LNbitsError(f"Invalid lightning address format: {lightning_address}")
        try:
            user, domain = lightning_address.split("@")
            well_known_url = f"https://{domain}/.well-known/lnurlp/{user}"
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.get(well_known_url)
                if response.status_code != 200:
                    return None
                lnurl_data = response.json()
                if not all(
                    k in lnurl_data for k in ("callback", "minSendable", "maxSendable")
                ):
                    return None
                return lnurl_data["callback"]
        except Exception as e:
            logger.error("Error resolving lightning address", error=str(e))
            return None

    async def get_lnurl_pay_invoice(
        self, callback_url: str, amount_msats: int, comment: Optional[str] = None
    ) -> Optional[str]:
        """Get invoice from LNURL-pay callback."""
        try:
            params: Dict[str, Any] = {"amount": amount_msats}
            if comment:
                params["comment"] = comment
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.get(callback_url, params=params)
                if response.status_code != 200:
                    return None
                data = response.json()
                if "reason" in data:
                    return None
                return data.get("pr")
        except Exception as e:
            logger.error("Error getting LNURL-pay invoice", error=str(e))
            return None

    async def pay_lightning_address(
        self, lightning_address: str, amount_sats: int, comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """Resolve → callback → invoice → pay."""
        amount_msats = amount_sats * 1000
        callback_url = await self.resolve_lightning_address(lightning_address)
        if not callback_url:
            raise LNbitsError(f"Failed to resolve lightning address: {lightning_address}")
        invoice = await self.get_lnurl_pay_invoice(callback_url, amount_msats, comment)
        if not invoice:
            raise LNbitsError(f"Failed to get invoice for: {lightning_address}")
        return await self.post("/api/v1/payments", json={"out": True, "bolt11": invoice})

    async def check_connection(self) -> bool:
        try:
            await self.get("/api/v1/wallet")
            return True
        except Exception:
            return False
