from uuid import UUID

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_token
from app.models.family import FamilyMember
from app.realtime.hub import hub

router = APIRouter(tags=["realtime"])


@router.websocket("/api/ws/families/{family_id}")
async def family_ws(
    websocket: WebSocket,
    family_id: UUID,
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> None:
    try:
        user_id = decode_token(token, "access")
    except ValueError:
        await websocket.close(code=4401)
        return
    member = (
        db.query(FamilyMember)
        .filter(FamilyMember.family_id == family_id, FamilyMember.user_id == user_id)
        .first()
    )
    if member is None:
        await websocket.close(code=4403)
        return

    await hub.connect(family_id, user_id, websocket)
    try:
        while True:
            # Keep-alive / ignore client messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(family_id, user_id, websocket)
