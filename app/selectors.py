from app.db import SessionLocal
from app.models import LearnedSelector

STABILITY_THRESHOLD = 2


def get_verified_selectors(url: str) -> dict | None:
    with SessionLocal() as db:
        row = db.get(LearnedSelector, url)
        if not row or not row.verified:
            return None
        return {
            "item_selector": row.item_selector,
            "title_selector": row.title_selector,
            "link_selector": row.link_selector,
            "location_selector": row.location_selector,
        }


def record_inferred_selectors(url: str, selectors: dict) -> None:
    with SessionLocal() as db:
        row = db.get(LearnedSelector, url)
        if (
            row
            and row.item_selector == selectors["item_selector"]
            and row.title_selector == selectors["title_selector"]
            and row.link_selector == selectors["link_selector"]
            and row.location_selector == selectors.get("location_selector")
        ):
            row.stable_count += 1
            if row.stable_count >= STABILITY_THRESHOLD:
                row.verified = True
        else:
            row = LearnedSelector(
                url=url,
                item_selector=selectors["item_selector"],
                title_selector=selectors["title_selector"],
                link_selector=selectors["link_selector"],
                location_selector=selectors.get("location_selector"),
                stable_count=1,
                verified=False,
            )
        db.merge(row)
        db.commit()
