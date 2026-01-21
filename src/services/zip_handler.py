"""ZIP file handling service"""

import logging
import os
import zipfile

from src.config.exception_config import ZipExtractionError

logger = logging.getLogger(__name__)


async def extract_zip(zip_path: str, extract_dir: str) -> str:
    """
    Extract ZIP file and return the project root directory.

    Args:
        zip_path: Path to the ZIP file
        extract_dir: Directory to extract to

    Returns:
        Path to the project root directory (handles nested directories)

    Raises:
        ZipExtractionError: If extraction fails
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            # Check for unsafe paths
            for member in zip_ref.namelist():
                if member.startswith("/") or ".." in member:
                    raise ZipExtractionError(f"Unsafe path in ZIP: {member}")

            zip_ref.extractall(extract_dir)
            logger.info(f"Extracted {len(zip_ref.namelist())} files to {extract_dir}")

        # Find the actual project root
        # Handle case where ZIP contains a single top-level directory
        extracted_items = os.listdir(extract_dir)

        if len(extracted_items) == 1:
            single_item = os.path.join(extract_dir, extracted_items[0])
            if os.path.isdir(single_item):
                # Check if it looks like a project root
                if _is_project_root(single_item):
                    return single_item

        # Otherwise, use extract_dir as project root
        return extract_dir

    except zipfile.BadZipFile as e:
        raise ZipExtractionError(f"Invalid ZIP file: {e}")
    except Exception as e:
        raise ZipExtractionError(f"Failed to extract ZIP: {e}")


def _is_project_root(path: str) -> bool:
    """
    Check if a directory looks like a project root.

    Looks for common project files like package.json, pyproject.toml, etc.
    """
    project_indicators = [
        "package.json",
        "pyproject.toml",
        "setup.py",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "Makefile",
        "README.md",
        "src",
        "lib",
        "app",
    ]

    for indicator in project_indicators:
        if os.path.exists(os.path.join(path, indicator)):
            return True

    return False
