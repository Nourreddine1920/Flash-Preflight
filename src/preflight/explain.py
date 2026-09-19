"""`--explain <rule-id>`: per-rule documentation, offline.

Built-in rule docs ship inside the package (preflight/rule_docs/<ID>.md) so they
work after a plain `pip install`, not only in a source checkout. A plugin rule
can provide its own text via a `docs` class attribute; otherwise its
one-line `description` is shown.
"""

from __future__ import annotations

from importlib.resources import files

from preflight.rules.base import Rule


def get_doc(cls: type[Rule]) -> str:
    packaged = files("preflight").joinpath("rule_docs", f"{cls.id}.md")
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    docs = getattr(cls, "docs", None)
    if isinstance(docs, str) and docs.strip():
        return docs
    return (
        f"# {cls.id}  {cls.name}\n\n{cls.description}\n\n"
        "(This rule provides no extended documentation.)\n"
    )
