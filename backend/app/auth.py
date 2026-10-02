"""Demo identity: a signed session cookie that references a fixed server-side identity.

This proves authorization behaviour, not authentication security. Anyone using the
local demo can pick either identity.
"""

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel

from .config import ALLOWED_ORIGINS, SESSION_SECRET

COOKIE_NAME = "demo_session"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class Identity:
    id: str
    name: str
    role: Literal["viewer", "reviewer"]

    @property
    def can_mutate(self) -> bool:
        return self.role == "reviewer"


IDENTITIES: dict[str, Identity] = {
    "viewer": Identity(id="viewer", name="Vera Viewer", role="viewer"),
    "reviewer": Identity(id="reviewer", name="Riley Reviewer", role="reviewer"),
}

_serializer = URLSafeSerializer(SESSION_SECRET, salt="demo-session")


def is_cross_origin_mutation(request: Request) -> bool:
    if request.method not in UNSAFE_METHODS:
        return False
    origin = request.headers.get("origin")
    if origin is not None:
        return origin not in ALLOWED_ORIGINS
    return request.headers.get("sec-fetch-site") == "cross-site"


def current_identity(request: Request) -> Identity:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="No demo session. Choose a demo identity.")
    try:
        identity_id = _serializer.loads(token)
    except BadSignature:
        raise HTTPException(status_code=401, detail="Invalid demo session. Choose a demo identity.")
    identity = IDENTITIES.get(identity_id) if isinstance(identity_id, str) else None
    if identity is None:
        raise HTTPException(status_code=401, detail="Unknown demo identity.")
    return identity


def require_reviewer(identity: Annotated[Identity, Depends(current_identity)]) -> Identity:
    if not identity.can_mutate:
        raise HTTPException(status_code=403, detail="Only the reviewer identity can make changes.")
    return identity


CurrentUser = Annotated[Identity, Depends(current_identity)]
Reviewer = Annotated[Identity, Depends(require_reviewer)]


class IdentityOut(BaseModel):
    id: str
    name: str
    role: str
    can_mutate: bool


class SessionIn(BaseModel):
    identity: Literal["viewer", "reviewer"]


def _identity_out(identity: Identity) -> IdentityOut:
    return IdentityOut(
        id=identity.id, name=identity.name, role=identity.role, can_mutate=identity.can_mutate
    )


router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.get("/identities", response_model=list[IdentityOut])
def list_identities() -> list[IdentityOut]:
    return [_identity_out(identity) for identity in IDENTITIES.values()]


@router.get("/session", response_model=IdentityOut)
def get_session(identity: CurrentUser) -> IdentityOut:
    return _identity_out(identity)


@router.post("/session", response_model=IdentityOut)
def start_session(body: SessionIn, response: Response) -> IdentityOut:
    identity = IDENTITIES[body.identity]
    response.set_cookie(
        COOKIE_NAME,
        _serializer.dumps(identity.id),
        httponly=True,
        samesite="strict",
        path="/",
    )
    return _identity_out(identity)


@router.delete("/session", status_code=204)
def end_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
