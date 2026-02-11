"""Pydantic models — trimmed to config-related models only.

All API response models are no longer needed since the generic dispatcher
returns raw JSON from the LNbits API.
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, HttpUrl, validator


class ConfigureLNbitsRequest(BaseModel):
    """Request model for configuring LNbits connection."""

    lnbits_url: Optional[HttpUrl] = Field(
        description="Base URL for LNbits instance", default=None
    )
    api_key: Optional[str] = Field(
        description="API key for LNbits authentication", default=None
    )
    bearer_token: Optional[str] = Field(
        description="Bearer token for authentication", default=None
    )
    oauth2_token: Optional[str] = Field(
        description="OAuth2 token for authentication", default=None
    )
    auth_method: Optional[str] = Field(
        description="Authentication method", default=None
    )
    timeout: Optional[int] = Field(
        description="Request timeout in seconds", default=None, ge=1, le=300
    )
    rate_limit_per_minute: Optional[int] = Field(
        description="Rate limit per minute", default=None, ge=1, le=1000
    )

    @validator("auth_method")
    def validate_auth_method(cls, v):
        if v is not None:
            valid = ["api_key_header", "api_key_query", "http_bearer", "oauth2"]
            if v not in valid:
                raise ValueError(f"auth_method must be one of: {valid}")
        return v

    class Config:
        extra = "forbid"


class ConfigurationStatusResponse(BaseModel):
    is_configured: bool = Field(description="Whether runtime configuration is active")
    config: Dict[str, Any] = Field(description="Current configuration (masked)")

    class Config:
        extra = "allow"


class ConfigurationTestResponse(BaseModel):
    success: bool = Field(description="Test success status")
    message: str = Field(description="Test result message")
    wallet_info: Optional[Dict[str, Any]] = Field(default=None)
    error: Optional[str] = Field(default=None)

    class Config:
        extra = "allow"
