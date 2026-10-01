import io
import itertools
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from synthetic import default_book, write_book

from brickwise import __version__
from brickwise.server import Server

ENGINE = Path(__file__).resolve().parent.parent


class Lines(io.StringIO):
    """Collects what the server writes, safely across its threads."""

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()

    def write(self, s):
        with self.lock:
            return super().write(s)

    def messages(self):
        with self.lock:
            return [json.loads(line) for line in self.getvalue().splitlines()]


@pytest.fixture(scope="module")
def book_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("books") / "book.pdf"
    write_book(str(path), default_book())
    return str(path)


@pytest.fixture
def server(tmp_path):
    out = Lines()
    srv = Server(tmp_path / "library", out)
    srv.out_lines = out
    yield srv
    srv.stop()


_ids = itertools.count(1)


def call(srv, method, **params):
    rid = next(_ids)
    srv.handle(json.dumps({"id": rid, "method": method, "params": params}))
    [reply] = [m for m in srv.out_lines.messages() if m.get("id") == rid]
    return reply


def test_import_runs_in_the_background_and_reports_progress(server, book_pdf):
    job = call(server, "import_pdf", path=book_pdf)["result"]
    assert job["state"] == "queued"
    assert server.wait_idle()
    events = [m["job"] for m in server.out_lines.messages() if m.get("event") == "job"]
    states = [e["state"] for e in events]
    assert states[-1] == "done", events[-1]
    assert "running" in states
    assert any(0 < e["fraction"] < 1 for e in events)
    set_id = events[-1]["set_id"]

    [s] = call(server, "list_sets")["result"]
    assert s["id"] == set_id
    assert call(server, "get_set", set_id=set_id)["result"]["parts"] == 5

    call(server, "import_pdf", path=book_pdf)
    assert server.wait_idle()
    assert [j["state"] for j in call(server, "jobs")["result"]] == ["done", "exists"]
    call(server, "dismiss", job_id=job["id"])
    assert [j["state"] for j in call(server, "jobs")["result"]] == ["exists"]


def test_failed_import_is_reported(server, tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    call(server, "import_pdf", path=str(bad))
    assert server.wait_idle()
    [job] = call(server, "jobs")["result"]
    assert job["state"] == "failed"
    assert "can't be read as a PDF" in job["error"]


def test_queued_import_can_be_cancelled(server, book_pdf):
    call(server, "import_pdf", path=book_pdf)
    second = call(server, "import_pdf", path=book_pdf)["result"]
    call(server, "cancel", job_id=second["id"])
    assert server.wait_idle()
    states = [j["state"] for j in call(server, "jobs")["result"]]
    assert states == ["done", "cancelled"]


def test_errors_come_back_as_messages(server):
    assert call(server, "get_set", set_id=99)["error"]["message"] == "That set is no longer in the library."
    assert "unknown method" in call(server, "drop_tables")["error"]["message"]
    assert "unexpected keyword" in call(server, "list_sets", nope=1)["error"]["message"]


def test_serve_speaks_json_lines_over_stdio(tmp_path):
    proc = subprocess.Popen(
        [sys.executable, "-m", "brickwise", "serve", "--library", str(tmp_path / "library")],
        cwd=ENGINE,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    proc.stdin.write('{"id": 1, "method": "version"}\n{"id": 2, "method": "list_sets"}\n')
    proc.stdin.close()
    lines = [json.loads(line) for line in proc.stdout]
    assert proc.wait(timeout=30) == 0
    assert lines == [
        {"id": 1, "result": {"engine": __version__, "library": str(tmp_path / "library")}},
        {"id": 2, "result": []},
    ]
