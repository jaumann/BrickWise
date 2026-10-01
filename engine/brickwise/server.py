"""JSON over stdio, for the desktop app.

The app starts `brickwise serve --library DIR` and writes one JSON request per
line to its stdin:

    {"id": 1, "method": "list_sets", "params": {}}

Each request gets one line back on stdout, either

    {"id": 1, "result": ...}   or   {"id": 1, "error": {"message": "..."}}

Imports run one at a time in a separate process, so a crash or a cancel never
takes the server down and pdfium is never used from two threads. Their
progress arrives as event lines without an id:

    {"event": "job", "job": {"id": 3, "state": "running", "stage": "...", "fraction": 0.4, ...}}
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO

from . import __version__
from .library import Library, LibraryError


def engine_command() -> list[str]:
    """How to start this engine again, whether frozen into an app or run from source."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "brickwise"]


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    if not getattr(sys, "frozen", False):
        # Find this copy of the package even when it isn't installed.
        here = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = os.pathsep.join(p for p in (here, env.get("PYTHONPATH")) if p)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


@dataclass
class Job:
    id: int
    path: str
    name: str
    state: str = "queued"  # queued, running, done, exists, failed, cancelled
    stage: str = ""
    fraction: float = 0.0
    set_id: int | None = None
    error: str | None = None


class Server:
    METHODS = (
        "version",
        "list_sets",
        "get_set",
        "import_pdf",
        "jobs",
        "cancel",
        "dismiss",
        "review",
        "reassign",
        "place",
        "unplace",
        "accept",
        "rename",
        "delete",
        "page_image",
    )

    def __init__(self, root: str | os.PathLike, out: IO[str]):
        self.root = Path(root)
        self.lib = Library(root)
        self.lib.clean_up()
        self.out = out
        self._out_lock = threading.Lock()
        self._jobs: dict[int, Job] = {}
        self._next_job = 1
        self._queue: queue.Queue[Job | None] = queue.Queue()
        self._proc: subprocess.Popen | None = None
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()

    # -- protocol --------------------------------------------------------

    def send(self, msg: dict) -> None:
        line = json.dumps(msg, separators=(",", ":"))
        with self._out_lock:
            self.out.write(line + "\n")
            self.out.flush()

    def handle(self, line: str) -> None:
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            self.send({"id": None, "error": {"message": "not JSON"}})
            return
        rid = req.get("id")
        method = req.get("method")
        if method not in self.METHODS:
            self.send({"id": rid, "error": {"message": f"unknown method {method!r}"}})
            return
        try:
            result = getattr(self, method)(**(req.get("params") or {}))
        except LibraryError as e:
            self.send({"id": rid, "error": {"message": str(e)}})
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            self.send({"id": rid, "error": {"message": f"{type(e).__name__}: {e}"}})
        else:
            self.send({"id": rid, "result": result})

    def run(self, inp: IO[str]) -> None:
        try:
            for line in inp:
                if line.strip():
                    self.handle(line)
        finally:
            self.stop()

    def stop(self) -> None:
        self._queue.put(None)
        for job in self._jobs.values():
            if job.state == "queued":
                job.state = "cancelled"
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
        self._worker.join(timeout=10)
        self.lib.close()

    # -- methods ---------------------------------------------------------

    def version(self) -> dict:
        return {"engine": __version__, "library": str(self.root)}

    def list_sets(self) -> list[dict]:
        return self.lib.list_sets()

    def get_set(self, set_id: int) -> dict:
        return self.lib.get_set(set_id)

    def review(self, set_id: int) -> dict:
        return self.lib.review(set_id)

    def reassign(self, set_id: int, picture: str, element_id: str) -> dict:
        return self.lib.reassign(set_id, picture, element_id)

    def place(self, set_id: int, element_id: str, step_id: int | None = None, bag: int | None = None) -> dict:
        return self.lib.place(set_id, element_id, step_id, bag)

    def unplace(self, set_id: int, callout_id: int) -> dict:
        return self.lib.unplace(set_id, callout_id)

    def accept(self, set_id: int, element_id: str | None = None, accepted: bool = True) -> dict:
        return self.lib.accept(set_id, element_id, accepted)

    def rename(self, set_id: int, name: str) -> dict:
        return self.lib.rename(set_id, name)

    def delete(self, set_id: int) -> None:
        self.lib.delete(set_id)

    def page_image(self, set_id: int, page: int) -> dict:
        return self.lib.page_image(set_id, page)

    def import_pdf(self, path: str) -> dict:
        job = Job(self._next_job, os.path.abspath(path), os.path.basename(path))
        self._next_job += 1
        self._jobs[job.id] = job
        self._queue.put(job)
        self._event(job)
        return asdict(job)

    def jobs(self) -> list[dict]:
        return [asdict(j) for j in self._jobs.values()]

    def cancel(self, job_id: int) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.state not in ("queued", "running"):
            return
        if job.state == "running" and self._proc is not None:
            self._proc.terminate()
        job.state = "cancelled"
        self._event(job)

    def dismiss(self, job_id: int) -> None:
        job = self._jobs.get(job_id)
        if job is not None and job.state not in ("queued", "running"):
            del self._jobs[job_id]

    # -- import worker ---------------------------------------------------

    def _event(self, job: Job) -> None:
        self.send({"event": "job", "job": asdict(job)})

    def wait_idle(self, timeout: float = 120) -> bool:
        """For tests: wait until no import is queued or running."""
        end = time.monotonic() + timeout
        while any(j.state in ("queued", "running") for j in list(self._jobs.values())):
            if time.monotonic() > end:
                return False
            time.sleep(0.05)
        return True

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            if job.state == "queued":
                self._run(job)

    def _run(self, job: Job) -> None:
        job.state = "running"
        self._event(job)
        cmd = [*engine_command(), "import", "--library", str(self.root), "--jsonl", job.path]
        last = (job.stage, job.fraction)
        result: dict = {}
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=_child_env(),
            )
            if job.state == "cancelled":  # cancelled while the process was starting
                self._proc.terminate()
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # stray output from a library
                if "stage" in msg:
                    job.stage, job.fraction = msg["stage"], float(msg["fraction"])
                    # Keep events to a trickle: every stage, then each 1% step.
                    if job.state == "running" and (job.stage != last[0] or job.fraction - last[1] >= 0.01):
                        last = (job.stage, job.fraction)
                        self._event(job)
                else:
                    result = msg
            self._proc.wait()
        except OSError as e:
            result = {"error": f"could not start the import: {e}"}
        finally:
            self._proc = None
        if job.state == "cancelled":
            self.lib.clean_up()
        elif "set_id" in result:
            job.state = "done" if result.get("new") else "exists"
            job.set_id = result["set_id"]
            job.fraction = 1.0
        else:
            job.state = "failed"
            job.error = result.get("error") or "The import stopped unexpectedly."
            self.lib.clean_up()
        self._event(job)


def serve(root: str) -> int:
    # Keep the real stdout for the protocol and send anything else that gets
    # printed (by us or by a native library) to stderr instead.
    proto = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", newline="\n")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    inp = open(sys.stdin.fileno(), encoding="utf-8", closefd=False)
    Server(root, proto).run(inp)
    return 0
