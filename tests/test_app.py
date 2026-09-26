from fastapi.testclient import TestClient

from sad_generator import __version__
from sad_generator.app import app
from sad_generator.sad_builder import create_input_template

client = TestClient(app)


def _upload(path="/generate", content=None, name="in.xls", **params):
    content = content if content is not None else create_input_template()
    return client.post(path, params=params, files={"file": (name, content, "application/vnd.ms-excel")})


def test_home_and_health():
    r = client.get("/")
    assert r.status_code == 200 and f"v{__version__}" in r.text and "{{VERSION}}" not in r.text
    assert client.get("/api/health").json()["version"] == __version__


def test_template_download():
    r = client.get("/download-template")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.ms-excel"


def test_preview():
    r = _upload("/api/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["stats"]["total_items"] == 1
    assert body["items"][0]["hs_code"] == "0603120011"


def test_generate_upload_download_history_delete():
    r = _upload(preferential="safta")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bl_number"] == "BL123456"
    assert body["duty_summary"]["preferential"] == "safta"
    assert body["duty_summary"]["total_duty"] == 500.0      # 10% SAFTA on 5000
    dl = client.get(body["download_url"])
    assert dl.status_code == 200 and len(dl.content) > 1000

    names = [f["name"] for f in client.get("/api/history").json()["files"]]
    fname = body["download_url"].rsplit("/", 1)[1]
    assert fname in names
    assert client.delete(f"/output/{fname}").status_code == 200
    assert client.get(body["download_url"]).status_code == 404


def test_generate_manual():
    r = client.post("/api/generate-manual", json={
        "general": {"bl_number": "MAN/1", "invoice_currency": "MVR"},
        "items": [{"hs_code": "6403990099", "description": "Sandals", "item_price": 100, "duty_rate": "20%"}],
        "preferential": "cmfta",
    })
    assert r.status_code == 200, r.text
    ds = r.json()["duty_summary"]
    assert ds["total_duty"] == 5.0 and ds["currency"] == "MVR"


def test_rejects_bad_input():
    assert _upload(name="notes.txt", content=b"hello").status_code == 415
    assert _upload(content=b"not excel").status_code == 422
    assert _upload(preferential="bogus").status_code == 422
    assert client.post("/api/generate-manual", json={"items": []}).status_code == 422


def test_output_path_traversal_blocked():
    assert client.get("/output/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert client.get("/output/nope.xls").status_code == 404


def test_hs_endpoints():
    r = client.get("/api/hs-lookup", params={"description": "rice"})
    assert r.json()["results"][0]["hs_code"] == "1006300099"
    assert client.get("/api/hs-tariff/6403990099").json()["duty_rate"] == 20.0
    assert client.get("/api/hs-tariff/1234").status_code == 404
