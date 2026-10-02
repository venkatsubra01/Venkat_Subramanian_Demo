from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import activity, auth, chargebacks, kyc, refunds
from .db import create_tables


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    yield


app = FastAPI(title="Ops internal tools (local demo)", lifespan=lifespan)


@app.middleware("http")
async def reject_cross_origin_mutations(request: Request, call_next):
    if auth.is_cross_origin_mutation(request):
        return JSONResponse(status_code=403, content={"detail": "Cross-origin request rejected."})
    return await call_next(request)


app.include_router(auth.router)
app.include_router(kyc.router)
app.include_router(refunds.router)
app.include_router(refunds.events_router)
app.include_router(chargebacks.router)
app.include_router(activity.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
