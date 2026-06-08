"""Prompt registry: load versioned markdown prompts by key.

Prompts live as ``<key>.<version>.md`` under ``templates/``. Templates use
``str.format`` placeholders, so keep literal curly braces out of the markdown.
"""

from pathlib import Path

DEFAULT_TEMPLATES_DIR = Path(__file__).parent / "templates"


class PromptRegistry:
    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = base_dir or DEFAULT_TEMPLATES_DIR

    def get(self, key: str, version: str = "v1") -> str:
        """Return the raw template text for ``key`` at ``version``."""
        return (self._base / f"{key}.{version}.md").read_text(encoding="utf-8")

    def render(self, key: str, *, version: str = "v1", **values: object) -> str:
        """Return the template with ``{placeholders}`` substituted."""
        return self.get(key, version).format(**values)

    def render_map(self, key: str, values: dict[str, object], *, version: str = "v1") -> str:
        """Like ``render`` but takes a values mapping (handy for computed kwargs)."""
        return self.get(key, version).format(**values)
