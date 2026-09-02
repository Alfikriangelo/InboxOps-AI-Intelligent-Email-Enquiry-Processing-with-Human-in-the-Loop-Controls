from fastapi import APIRouter
from app.core.config import settings
from app.services.routing_service import score_teams

router = APIRouter(prefix="/api/v1/teams", tags=["teams"])

@router.get("")
def list_teams():
    descs = settings.TEAM_DESCRIPTIONS
    owners = settings.TEAM_OWNERS
    return [
        {"team": k, "owner": owners.get(k), "description": descs.get(k)}
        for k in descs.keys()
    ]

@router.post("/route-preview")
def route_preview(payload: dict):
    # payload: {"message": "text", "intent_keywords": ["a","b"], "intent": "text", "classification": "sales", "source": "messaging"}
    from app.services.routing_service import route_team, explain_routing
    from app.models.schemas import ClassificationEnum
    query = payload.get("message") or " ".join(payload.get("intent_keywords", [])) + " " + (payload.get("intent") or "")
    classification = payload.get("classification")
    source = payload.get("source")
    try:
        cls = ClassificationEnum(classification) if classification else None
    except Exception:
        cls = None
    team = route_team(query, cls, source=source)
    scores = explain_routing(query, source=source)
    return {"suggested_team": team.value, "scores": scores}
