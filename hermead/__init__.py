"""HermeAd: Hermes Agent plugin for project-level linting, type-checking, formatting, and security scanning.

Runs entirely through Hermes hook system. No external API, no MCP server, no web server.
"""

from hermead.hooks import post_tool_call

__version__ = "0.1.0"


def register():
    """Register HermeAd hooks with the Hermes Agent plugin system.

    Returns the hook registration dict expected by Hermes Agent.
    """
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
