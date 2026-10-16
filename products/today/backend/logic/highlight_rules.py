import re


def short(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).replace('"', "").strip()
    text = re.sub(r"'([^']*)'", "‘\\1’", text).replace("'", "’")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:(-– ")
