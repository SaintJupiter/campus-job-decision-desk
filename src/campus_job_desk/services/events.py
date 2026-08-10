from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from campus_job_desk.models import DecisionEvent


def record_event(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    event_type: str,
    payload: dict[str, Any],
    actor: str = "user",
) -> DecisionEvent:
    event = DecisionEvent(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        actor=actor,
        payload=json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )
    session.add(event)
    return event
