"""HermeAd: Hermes Agent plugin for project-level linting, type-checking, formatting, and security scanning.

Runs entirely through Hermes hook system. No external API, no MCP server, no web server.
"""

from __future__ import annotations

import logging
from typing import Any

from hermead.hooks import post_tool_call
from hermead.slash_commands import handle as handle_slash_command

logger = logging.getLogger(__name__)

__version__ = "0.1.0"


def register(ctx: Any | None = None) -> dict[str, Any] | None:
    """Register HermeAd hooks and slash commands with the Hermes Agent plugin system.

    Supports both:
    - New ctx-based API (ctx.register_hook, ctx.register_command)
    - Legacy dict-return API for backward compatibility
    """
    if ctx is not None:
        # New ctx-based API
        ctx.register_hook("post_tool_call", post_tool_call)
        ctx.register_command(
            "hermead",
            handler=handle_slash_command,
            description="Run HermeAd checks and view config/status",
        )
        return None
    else:
        # Legacy API: return registration dict
        return {
            "hooks": {
                "post_tool_call": post_tool_call,
            },
            "metadata": {
                "name": "hermead",
                "version": __version__,
                "description": (
                    "Post-tool-call hook that detects write_file/patch on project "
                    "files and auto-runs linting, type-checking, formatting, and "
                    "security checks."
                ),
            },
        }
