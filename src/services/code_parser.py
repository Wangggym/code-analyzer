"""Code parsing and structure extraction service"""

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# File extensions to include in analysis
CODE_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx",  # TypeScript/JavaScript
    ".py",  # Python
    ".rs",  # Rust
    ".go",  # Go
    ".java",  # Java
    ".kt",  # Kotlin
    ".swift",  # Swift
    ".rb",  # Ruby
    ".php",  # PHP
    ".cs",  # C#
    ".cpp", ".c", ".h", ".hpp",  # C/C++
}

# Directories to skip
SKIP_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    "target",
    "vendor",
}

# Files to skip
SKIP_FILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "uv.lock",
    "Cargo.lock",
}


@dataclass
class FileInfo:
    """Information about a source file"""

    path: str  # Relative path from project root
    extension: str
    content: str
    line_count: int


@dataclass
class ProjectStructure:
    """Structure of the project"""

    root_dir: str
    files: list[FileInfo] = field(default_factory=list)
    project_type: str = "unknown"  # nodejs, python, rust, etc.
    config_files: list[str] = field(default_factory=list)  # package.json, pyproject.toml, etc.


async def parse_project(project_dir: str) -> ProjectStructure:
    """
    Parse project structure and extract code files.

    Args:
        project_dir: Path to the project root directory

    Returns:
        ProjectStructure with all relevant source files
    """
    structure = ProjectStructure(root_dir=project_dir)

    # Detect project type
    structure.project_type = _detect_project_type(project_dir)
    logger.info(f"Detected project type: {structure.project_type}")

    # Walk through directory
    for root, dirs, files in os.walk(project_dir):
        # Skip certain directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for filename in files:
            # Skip certain files
            if filename in SKIP_FILES:
                continue

            file_path = os.path.join(root, filename)
            relative_path = os.path.relpath(file_path, project_dir)
            _, ext = os.path.splitext(filename)

            # Track config files
            if filename in ["package.json", "pyproject.toml", "Cargo.toml", "go.mod"]:
                structure.config_files.append(relative_path)

            # Only include code files
            if ext not in CODE_EXTENSIONS:
                continue

            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                # Skip very large files (> 100KB)
                if len(content) > 100 * 1024:
                    logger.warning(f"Skipping large file: {relative_path}")
                    continue

                structure.files.append(
                    FileInfo(
                        path=relative_path,
                        extension=ext,
                        content=content,
                        line_count=content.count("\n") + 1,
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to read {relative_path}: {e}")

    logger.info(f"Parsed {len(structure.files)} source files")
    return structure


def _detect_project_type(project_dir: str) -> str:
    """Detect the type of project based on config files"""
    config_map = {
        "package.json": "nodejs",
        "pyproject.toml": "python",
        "setup.py": "python",
        "Cargo.toml": "rust",
        "go.mod": "go",
        "pom.xml": "java",
        "build.gradle": "java",
    }

    for config_file, project_type in config_map.items():
        if os.path.exists(os.path.join(project_dir, config_file)):
            return project_type

    return "unknown"


def format_code_for_llm(structure: ProjectStructure, max_chars: int = 100000) -> str:
    """
    Format project code for LLM analysis.

    Args:
        structure: Parsed project structure
        max_chars: Maximum characters to include

    Returns:
        Formatted string with file contents
    """
    output_parts = []
    current_chars = 0

    # Add project overview
    header = f"""# Project Analysis
Project Type: {structure.project_type}
Total Files: {len(structure.files)}
Config Files: {', '.join(structure.config_files)}

---
"""
    output_parts.append(header)
    current_chars += len(header)

    # Sort files by relevance (config files first, then by path)
    sorted_files = sorted(
        structure.files,
        key=lambda f: (
            0 if f.path in structure.config_files else 1,
            f.path,
        ),
    )

    for file_info in sorted_files:
        file_section = f"""
## File: {file_info.path}
```{file_info.extension.lstrip('.')}
{file_info.content}
```
"""
        if current_chars + len(file_section) > max_chars:
            logger.warning(f"Truncating output at {current_chars} chars")
            break

        output_parts.append(file_section)
        current_chars += len(file_section)

    return "".join(output_parts)
