from __future__ import annotations

import queue
import threading
from collections.abc import Callable


class JobQueue:
    def __init__(self, poll_seconds: float = 0.5) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._poll_seconds = poll_seconds
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._processor: Callable[[str], None] | None = None

    def start(self, processor: Callable[[str], None]) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._processor = processor
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._run, name="job-worker", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2)

    def enqueue(self, job_id: str) -> None:
        self._queue.put(job_id)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id = self._queue.get(timeout=self._poll_seconds)
            except queue.Empty:
                continue
            try:
                if self._processor:
                    self._processor(job_id)
            finally:
                self._queue.task_done()
