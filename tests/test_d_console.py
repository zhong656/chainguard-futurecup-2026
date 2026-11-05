import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from web.demo_server import Handler, ThreadingHTTPServer


@pytest.fixture
def server():
    service = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{service.server_port}"
    service.shutdown()
    service.server_close()
    thread.join()


def test_console_sse_and_artifact_download(server):
    payload = json.dumps({"request": "机器视觉质检", "scenario": "numeric_conflict"}).encode()
    request = Request(server + "/api/run", data=payload, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=10) as response:
        assert response.headers.get_content_type() == "text/event-stream"
        chunks = response.read().decode().strip().split("\n\n")
    result = json.loads(chunks[-1].split("data: ", 1)[1])
    assert result["passed"] and result["scorecard"]["round"] == 1
    with urlopen(server + f"/download?run={result['download_id']}&file=trace.jsonl") as response:
        assert len(response.read().splitlines()) == len(result["events"])
    with urlopen(server + "/api/workflow") as response:
        assert len(json.load(response)["nodes"]) == 11


@pytest.mark.parametrize("route", ["/../.git/config", "/download?run=../&file=trace.jsonl", "/download?run=abc&file=.env"])
def test_console_rejects_unknown_files(server, route):
    with pytest.raises(HTTPError):
        urlopen(server + route)


def test_console_rejects_cross_origin_submission(server):
    request = Request(server + "/api/run", data=b'{}',
                      headers={"Content-Type": "application/json", "Origin": "http://another.invalid"})
    with pytest.raises(HTTPError) as caught:
        urlopen(request)
    assert caught.value.code == 403
