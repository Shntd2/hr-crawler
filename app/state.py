import hashlib
from app.db import SessionLocal
from app.models import SourceState


def get_conditional_headers(url: str) -> dict:
    with SessionLocal() as db:
        st = db.get(SourceState, url)
        if not st:
            return {}
        headers = {}
        if st.etag:
            headers["If-None-Match"] = st.etag
        if st.last_modified:
            headers["If-Modified-Since"] = st.last_modified
        return headers


def save_validators(url: str, response_headers) -> None:
    with SessionLocal() as db:
        st = db.get(SourceState, url) or SourceState(url=url)
        if response_headers.get("etag"):
            st.etag = response_headers["etag"]
        if response_headers.get("last-modified"):
            st.last_modified = response_headers["last-modified"]
        db.merge(st)
        db.commit()


def content_changed(url: str, content: str) -> bool:
    h = hashlib.sha256(content.encode("utf-8", "ignore")).hexdigest()
    with SessionLocal() as db:
        st = db.get(SourceState, url) or SourceState(url=url)
        changed = st.content_hash != h
        st.content_hash = h
        db.merge(st)
        db.commit()
    return changed
