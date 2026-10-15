"""wsgi.py — production entrypoint (waitress, cross-platform).

    python wsgi.py
    # or: waitress-serve --host 0.0.0.0 --port 8080 wsgi:app
"""
import os

from waitress import serve

from app import app

if __name__ == "__main__":
    serve(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", 8080)),
        threads=int(os.environ.get("THREADS", 4)),
        # allow uploads up to ~100 MB (matches app-level limit)
        max_request_body_size=110 * 1024 * 1024,
    )
