"""The optional client handoff must label field outcomes as unverified."""

import io
import os
import re
import base64
import zlib

import app as m


def offline(*args, **kwargs):
    raise RuntimeError("network disabled in test")


m.requests.get = offline
client = m.app.test_client()
csv = (
    "datetime(utc),latitude,longitude,altitude(m),speed(mph),heading\n"
    "2026-01-15 18:00:00,34.0522,-118.2437,40,5,90\n"
    "2026-01-15 18:01:00,34.0523,-118.2436,41,5,90\n"
    "2026-01-15 18:02:00,34.0524,-118.2435,42,5,90\n"
    "2026-01-15 18:03:00,34.0525,-118.2434,43,5,90\n"
)

for slug in ("performance", "incident", "wind", "team"):
    page = client.get("/start/" + slug).get_data(as_text=True)
    assert 'name="service_use_case"' in page
    assert 'value="pet_search"' in page
    assert 'value="spraying"' in page
    assert 'value="inspection"' in page

original_dir = m.GENERATED_DIR
try:
    output_dir = os.path.join(os.path.dirname(__file__), "tmp", "pdfs")
    os.makedirs(output_dir, exist_ok=True)
    m.GENERATED_DIR = output_dir
    for use_case, title, incomplete in (
        ("pet_search", "Search Operation Handoff", "Search result / sighting"),
        ("spraying", "Spray Operation Handoff", "Treated area / dose"),
        ("inspection", "Asset Inspection Handoff", "Defect / severity"),
    ):
        before = set(os.listdir(output_dir))
        response = client.post(
            "/start/performance",
            data={
                "file": (io.BytesIO(csv.encode()), "sample.csv"),
                "service_use_case": use_case,
                "site_reference": "Case 123",
                "subject_reference": "Operator supplied reference",
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 200, (use_case, response.status_code)
        generated = set(os.listdir(output_dir)) - before
        paths = [os.path.join(output_dir, name) for name in generated if name.endswith(".pdf")]
        assert len(paths) == 1, (use_case, paths)
        with open(paths[0], "rb") as handle:
            pdf = handle.read()
        streams = []
        for stream in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
            try:
                streams.append(zlib.decompress(base64.a85decode(stream.strip(), adobe=True)))
            except (ValueError, zlib.error, OverflowError):
                continue
        text = b"\n".join(streams)
        assert title.encode() in text
        assert incomplete.encode() in text
        assert b"Operator review required" in text or b"Inspector review required" in text
        assert b"does not certify a search, treatment or defect finding" in text
        print("PASS", use_case, paths[0])
finally:
    m.GENERATED_DIR = original_dir
