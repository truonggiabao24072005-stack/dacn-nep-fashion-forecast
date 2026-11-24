"""Bounded parsing for identifiers supplied through URLs, forms and sessions."""


def positive_identifier(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    try:
        text = str(value)
    except ValueError:
        return None
    if not text.isascii() or not text.isdigit():
        return None
    canonical = text.lstrip("0") or "0"
    if len(canonical) > 19:
        return None
    number = int(canonical)
    return number if 0 < number <= 9_223_372_036_854_775_807 else None
