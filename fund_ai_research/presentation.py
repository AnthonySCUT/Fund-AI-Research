import re


_PARENTHETICAL_NOTE = re.compile(r"（[^（）]*）|\([^()]*\)")


def concise_source_label(source: str) -> str:
    """Hide parenthetical status notes in source labels shown on the page."""
    return _PARENTHETICAL_NOTE.sub("", source).strip()
