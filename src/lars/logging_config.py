"""Application logging configuration."""

import logging


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging with a consistent, parseable format."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
