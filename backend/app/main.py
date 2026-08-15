"""FastAPI application factory.

Two things are wired here and both are requirements rather than conveniences: every deliberate
refusal leaves as the typed envelope from ``app.errors``, and no unexpected exception ever
reaches a client as a stack trace.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errors import ErrorCode, ErrorEnvelope, MyoLensError
from app.routers import admin, calibrations, health, models, participants, sessions, uploads


class JsonFormatter(logging.Formatter):
    """Serialise the record with ``json.dumps`` rather than interpolating into a JSON-shaped
    template string.

    The template form was forgeable. It interpolated ``%(message)s`` straight between two literal
    quotes, and the refusal handler put the request path into that message -- so a caller who
    asked for a path containing a quote and a newline could close the string and inject their own
    keys:

        {"level":"INFO","message":"refusal code=not_found path=/v1/participants/a"b"forged":"yes"}

    That is not merely malformed output. Structured logs are read by machines, and a caller able
    to synthesise fields can plant a plausible entry or bury a real one. Escaping the path at the
    call site would fix this instance and leave the next one open; encoding at the formatter
    fixes the class, because every value now passes through a serialiser that cannot emit an
    unescaped quote or newline.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
logger = logging.getLogger("myolens")


def _require_deployable_configuration(settings) -> None:
    """Refuse to start a production container that cannot do its job.

    MYOLENS_STORAGE_BUCKET was missing from the Cloud Run deployment and nothing noticed. The
    service started, answered /v1/health with "ok", served the front end, authenticated users and
    created participants -- and returned 500 from every upload, because the object store was
    constructed lazily, on the first request that needed it, against a bucket with no name.

    Failing here converts that into a revision that never becomes healthy, which Cloud Run reports
    as a failed deploy. A misconfiguration should cost a red pipeline, not a silently useless
    service. Development is exempt: a local `uvicorn` for front-end work has no bucket and does
    not need one.
    """
    if settings.environment != "production":
        return
    missing = [
        name
        for name, value in (
            ("MYOLENS_STORAGE_BUCKET", settings.storage_bucket),
            ("MYOLENS_GCP_PROJECT_ID", settings.gcp_project_id),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Refusing to start in production without "
            + ", ".join(missing)
            + ". The service would answer /v1/health perfectly and fail every upload."
        )


def create_app() -> FastAPI:
    settings = get_settings()
    _require_deployable_configuration(settings)

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
        # The *route template*, never the concrete path. SRS 5.1: "Logs carry no participant
        # identifier -- a pseudonymous code plus a session time is still a re-identification
        # surface." A concrete path is exactly that: /v1/participants/<id> puts the id in the
        # log, and /v1/sessions/<id>/segment puts a session id there. The template keeps every
        # bit of the diagnostic value (which endpoint refused, and why) and carries no identifier.
        route = request.scope.get("route")
        logger.info(
            "refusal code=%s route=%s", exc.code.value, getattr(route, "path", "<unmatched>")
        )
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
    app.include_router(admin.router)
    app.include_router(participants.router)
    app.include_router(uploads.router)
    app.include_router(calibrations.router)
    app.include_router(sessions.router)
    logger.info("started environment=%s predictor=%s", settings.environment, settings.predictor)
    return app


app = create_app()
