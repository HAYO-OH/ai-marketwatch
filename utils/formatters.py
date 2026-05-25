def format_krw(value: int | float) -> str:
    return f"{int(value):,}원"


def truncate(text: str, max_len: int = 200) -> str:
    return text if len(text) <= max_len else text[:max_len] + "..."
