"""File utility functions"""

import os


def get_file_extension(filename: str) -> str:
    """Get file extension including the dot"""
    _, ext = os.path.splitext(filename)
    return ext.lower()


def is_binary_file(filepath: str) -> bool:
    """
    Check if a file is binary.

    Reads first 8KB and checks for null bytes.
    """
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk
    except Exception:
        return True


def safe_read_file(filepath: str, max_size: int = 100 * 1024) -> str | None:
    """
    Safely read a text file.

    Args:
        filepath: Path to the file
        max_size: Maximum file size to read (bytes)

    Returns:
        File content as string, or None if failed
    """
    try:
        if os.path.getsize(filepath) > max_size:
            return None

        if is_binary_file(filepath):
            return None

        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None


def count_lines(content: str) -> int:
    """Count lines in content"""
    return content.count("\n") + 1 if content else 0
