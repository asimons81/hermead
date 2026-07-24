"""Python file with intentional issues for testing.

Has lint violations, type errors, and a security issue.
"""

import os
import sys
from pathlib import Path
from typing import Any


def unused_function() -> None:
    """This function is never called - lint warning."""
    pass


def type_error_example(data: dict[str, Any]) -> str:
    """Type error: expects str return but returns int."""
    return 42


def unused_import() -> None:
    """Uses sys (imported but not at module level)."""
    sys.path.append("/tmp")


def hardcoded_password() -> str:
    """Security issue: hardcoded password (bandit B105)."""
    password = "supersecret123!"
    return password


class MyClass:
    """Minimal class definition."""

    def method_one(self) -> str:
        """Return a greeting."""
        return "hello"

    def method_two(self: Any) -> int:
        """Return a number."""
        return 0
