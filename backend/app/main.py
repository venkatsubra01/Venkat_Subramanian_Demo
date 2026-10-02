from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import activity, auth, chargebacks, kyc, refunds, work
from .activity import new_request_id, reset_request_id, set_request_id
from .migrations import upgrade


@asynccontextmanager
async def lifespan(_: FastAPI):
    upgrade()
    yield


app = FastAPI(title="Ops internal tools (local demo)", lifespan=lifespan)


@app.middleware("http")
async def reject_cross_origin_mutations(request: Request, call_next):
    if auth.is_cross_origin_mutation(request):
        return JSONResponse(status_code=403, content={"detail": "Cross-origin request rejected."})
    return await call_next(request)


@app.middleware("http")
async def request_id_context(request: Request, call_next):
    """Server-generated id shared by every activity entry written while handling this request."""
    request_id = new_request_id()
    token = set_request_id(request_id)
    try:
        response = await call_next(request)
    finally:
        reset_request_id(token)
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(auth.router)
app.include_router(kyc.router)
app.include_router(refunds.router)
app.include_router(refunds.events_router)
app.include_router(chargebacks.router)
app.include_router(activity.router)
app.include_router(activity.audit_router)
app.include_router(work.router)
app.include_router(work.approvals_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
