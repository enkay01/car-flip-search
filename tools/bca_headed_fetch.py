"""Compatibility entry point for the unified BCA capture CLI."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from car_flip_search.cli import main as cli_main


def main(argv: Sequence[str] | None = None) -> int:
    """Delegate legacy invocations to ``car-flip search-bca``."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    return cli_main(["search-bca", *arguments])


if __name__ == "__main__":
    sys.exit(main())
