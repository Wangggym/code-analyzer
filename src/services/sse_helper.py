"""SSE (Server-Sent Events) helper utilities"""

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class SSEEvent:
    """Server-Sent Event data"""

    stage: str
    message: str
    data: dict[str, Any] | None = None


def format_sse(event: SSEEvent) -> str:
    """Format SSEEvent as SSE text"""
    payload = {
        "stage": event.stage,
        "message": event.message,
    }
    if event.data:
        payload["data"] = event.data

    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# Stage definitions
class Stages:
    EXTRACTING = "extracting"
    ANALYZING_CODE = "analyzing_code"
    ANALYZING_STARTUP = "analyzing_startup"
    STARTING_PROJECT = "starting_project"
    WAITING_HEALTH = "waiting_health"
    GENERATING_TESTS = "generating_tests"
    RUNNING_TESTS = "running_tests"
    CLEANUP = "cleanup"
    COMPLETE = "complete"
    ERROR = "error"
