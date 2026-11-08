"""FastAPI dependencies and error mapping.

Error contract (so the UI can always explain what happened, in Spanish):

    LookupError      -> 404  (objeto inexistente o no publicado)
    PermissionError  -> 403  (falta consentimiento / token / alcance)
    ValueError       -> 422  (transición o dato inválido)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ids import stable_hash
from app.core.security import hash_token, token_matches
from app.domain.models import PartnerUser
from app.modules import funnel as funnel_service

from app.core.db import get_session

DbSession = Annotated[Session, Depends(get_session)]


def client_context(
    request: Request,
    x_prtds_session: Annotated[str | None, Header(alias="X-PRTDS-Session")] = None,
    x_prtds_actor: Annotated[str | None, Header(alias="X-PRTDS-Actor")] = None,
) -> dict[str, str | None]:
    """Pseudonymous session/actor references for the funnel ledger.

    The client supplies a random per-visit id; we never derive it from personal
    data and never store raw identifiers (§13.4).
    """
    session_ref = x_prtds_session or request.query_params.get("session_ref")
    if not session_ref:
        peer = request.client.host if request.client else "unknown"
        session_ref = "anon-" + stable_hash(peer, request.headers.get("user-agent", ""))[:16]
    return {"session_ref": session_ref, "actor_ref": x_prtds_actor}


ClientContext = Annotated[dict, Depends(client_context)]


def partner_from_token(
    session: DbSession,
    x_partner_token: Annotated[str | None, Header(alias="X-Partner-Token")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> PartnerUser:
    token = x_partner_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Falta el token del socio (X-Partner-Token).")

    candidates = session.query(PartnerUser).filter(PartnerUser.is_active.is_(True)).all()
    for user in candidates:
        if token_matches(token, user.token_hash):
            return user
    raise HTTPException(status_code=403, detail="Token de socio inválido o inactivo.")


PartnerUserDep = Annotated[PartnerUser, Depends(partner_from_token)]


def require_admin(
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> str:
    """Dev-only admin gate.

    Production must replace this with real identity + role separation (§13.4);
    the token itself is never stored in documents or in the repository.
    """
    if not x_admin_token or not token_matches(x_admin_token, hash_token(settings.demo_admin_token)):
        raise HTTPException(
            status_code=403, detail="Token de administración inválido (X-Admin-Token)."
        )
    return "admin"


AdminDep = Annotated[str, Depends(require_admin)]


def company_by_slug_or_404(session: Session, slug: str):
    company = funnel_service.company_by_slug(session, slug)
    if company is None:
        raise HTTPException(status_code=404, detail=f"Empresa inexistente: {slug}")
    return company
