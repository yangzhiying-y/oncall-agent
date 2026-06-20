"""Pure filename helpers that do not require databases or AI services."""


def get_file_extension(filename: str) -> str:
    """Return a lowercase extension without its leading dot."""
    parts = filename.rsplit(".", 1)
    return parts[1].lower() if len(parts) == 2 else ""


def sanitize_filename(filename: str) -> str:
    """Make an uploaded filename safe to join to the uploads directory."""
    sanitized = filename.replace(" ", "_")
    for char in ["\\", "/", ":", "*", "?", '"', "<", ">", "|"]:
        sanitized = sanitized.replace(char, "_")
    return sanitized
