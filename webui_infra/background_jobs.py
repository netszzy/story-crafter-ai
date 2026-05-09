"""Lightweight Streamlit-friendly background job state for V5.0-alpha1."""

from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BackgroundJob:
    name: str
    target: Callable[[threading.Event], Any]
    eta_seconds: int = 90
    on_success: Callable[[Any], None] | None = None
    on_error: Callable[[str], None] | None = None
    notify_success: Callable[[Any], None] | None = None
    notify_error: Callable[[str], None] | None = None
    notify_cancelled: Callable[[], None] | None = None
    started_at: float = field(default_factory=time.time)
    status: str = "pending"
    result: Any = None
    error: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread is not None:
            return
        self.status = "running"
        self.thread = threading.Thread(target=self._run, name=f"novel-job-{self.name}", daemon=True)
        self.thread.start()

    def cancel(self) -> None:
        self.cancel_event.set()
        if self.status == "running":
            self.status = "cancel_requested"

    def progress_ratio(self) -> float:
        if self.status == "done":
            return 1.0
        if self.status in {"error", "cancelled"}:
            return 0.0
        elapsed = time.time() - self.started_at
        return min(0.95, elapsed / max(1, self.eta_seconds))

    def elapsed_seconds(self) -> int:
        return int(time.time() - self.started_at)

    def _run(self) -> None:
        try:
            self.result = self.target(self.cancel_event)
            self.status = "cancelled" if self.cancel_event.is_set() else "done"
            if self.status == "done" and self.notify_success:
                self.notify_success(self.result)
            elif self.status == "cancelled" and self.notify_cancelled:
                self.notify_cancelled()
        except Exception:
            self.status = "error"
            self.error = traceback.format_exc(limit=8)
            if self.notify_error:
                self.notify_error(self.error)


def start_background_job(
    session_state: dict[str, Any],
    name: str,
    target: Callable[[threading.Event], Any],
    eta_seconds: int = 90,
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    notify_success: Callable[[Any], None] | None = None,
    notify_error: Callable[[str], None] | None = None,
    notify_cancelled: Callable[[], None] | None = None,
) -> BackgroundJob:
    job = BackgroundJob(
        name=name,
        target=target,
        eta_seconds=eta_seconds,
        on_success=on_success,
        on_error=on_error,
        notify_success=notify_success,
        notify_error=notify_error,
        notify_cancelled=notify_cancelled,
    )
    session_state["active_job"] = job
    job.start()
    return job
