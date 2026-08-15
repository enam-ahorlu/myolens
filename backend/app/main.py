"""FastAPI application factory.

Two things are wired here and both are requirements rather than conveniences: every deliberate
refusal leaves as the typed envelope from ``app.errors``, and no unexpected exception ever
reaches a client as a stack trace.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errors import ErrorCode, ErrorEnvelope, MyoLensError
from app.routers import calibrations, health, models, participants, sessions, uploads

# Structured, and deliberately free of participant identifiers. A pseudonymous code in a log line
# is still a re-identification surface once combined with a session time.
logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
logger = logging.getLogger("myolens")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="MyoLens API",
        version="1.0.0",
        description=(
            "Task-conditioned sEMG session analysis with reviewable automatic segmentation. "
            "Not a medical device. Not for diagnosis, treatment, or clinical decision-making."
        ),
    )

    origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # No cookies are used (ADR-004 is a bearer token, not a session cookie), so credentials
        # are never sent and never need to be allowed.
        allow_credentials=False,
        allow_methods=["*"],
        # Authorization carries the Firebase ID token; Content-Type is needed for JSON bodies.
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(MyoLensError)
    async def handle_refusal(request: Request, exc: MyoLensError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.info("refusal code=%s path=%s", exc.code.value, request.url.path)
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.envelope(request_id).model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        envelope = ErrorEnvelope(
            code=ErrorCode.VALIDATION_FAILED,
            message="The request body did not match the expected schema.",
            details=[
                {"field": ".".join(str(p) for p in e["loc"]), "problem": e["msg"]}
                for e in exc.errors()
            ],
            request_id=request_id,
        )
        return JSONResponse(status_code=422, content=envelope.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        # The trace goes to the log, where an operator can reach it. The client gets a code and
        # an identifier that ties their report to that log line.
        logger.exception("unhandled exception request_id=%s", request_id)
        envelope = ErrorEnvelope(
            code=ErrorCode.INTERNAL,
            message=(
                "Something went wrong on our side. Nothing was saved. "
                "Quote the request ID if you report this."
            ),
            request_id=request_id,
        )
        return JSONResponse(status_code=500, content=envelope.model_dump(mode="json"))

    app.include_router(health.router)
    app.include_router(models.router)
    app.include_router(participants.router)
    app.include_router(uploads.router)
    app.include_router(calibrations.router)
    app.include_router(sessions.router)
    logger.info("started environment=%s predictor=%s", settings.environment, settings.predictor)
    return app


app = create_app()
