"""Configuration helpers for the Better Blender MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BridgeConfig:
    """Runtime connection parameters for the Blender bridge."""

    host: str = "127.0.0.1"
    port: int = 8765
    token: str = "change-me"
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class AppConfig:
    """Top-level app configuration."""

    bridge: BridgeConfig


def load_config_from_env() -> AppConfig:
    """Load app configuration from environment variables."""

    host = os.getenv("BETTER_BLENDER_HOST", "127.0.0.1")
    port = int(os.getenv("BETTER_BLENDER_PORT", "8765"))
    token = os.getenv("BETTER_BLENDER_TOKEN", "change-me")
    timeout_seconds = float(os.getenv("BETTER_BLENDER_TIMEOUT", "30"))

    return AppConfig(
        bridge=BridgeConfig(
            host=host,
            port=port,
            token=token,
            timeout_seconds=timeout_seconds,
        )
    )
