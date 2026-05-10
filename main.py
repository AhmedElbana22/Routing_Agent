"""
main.py
FastAPI application entry point.

Endpoints:
  POST /chat                  -> main chat endpoint
  GET  /health                -> system health check
  GET  /session/{id}/clear    -> clear session memory
  GET  /                      -> basic info

Startup checks:
  - PostgreSQL connection (geo_tool + db_tool need it)
  - Routing engine reachability (routing_tool needs it)
  - Fare model availability (price_predictor)

CORS:
  Configured to allow Streamlit frontend (localhost:8501)
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager 
from pathlib import Path
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import sys
sys.path.append(str(Path(__file__).parent.resolve()))

import structlog

from config import settings, get_settings
from model.intent.schema import AgentResponse, ChatRequest, Language

logger = structlog.get_logger(__name__)

 
# Logging setup 

 
def _setup_logging() -> None:
    """
    Configure structlog for JSON logging in production,
    pretty console logging in development.
    """
    import logging
    import structlog

    log_level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(level=log_level)

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if settings.is_development:
        # Human-readable console output for dev
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        # JSON output for production
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

 
# Startup checks 


def _check_database() -> Dict[str, Any]:
    """
    Verify PostgreSQL connection on startup.
    Checks:
      - Basic connection via psycopg2
      - pg_trgm extension installed (geo_tool needs it)
      - PostGIS extension installed (geo_tool needs it)
      - stop table exists and has rows
    """
    import psycopg2

    result = {
        "connected":     False,
        "pg_trgm":       False,
        "postgis":       False,
        "stop_count":    0,
        "error":         None,
    }

    try:
        conn = psycopg2.connect(settings.db.dsn)
        conn.autocommit = True
        result["connected"] = True

        with conn.cursor() as cur:
            # Check pg_trgm
            cur.execute(
                "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm';"
            )
            result["pg_trgm"] = cur.fetchone() is not None

            # Check PostGIS
            cur.execute(
                "SELECT 1 FROM pg_extension WHERE extname = 'postgis';"
            )
            result["postgis"] = cur.fetchone() is not None

            # Check stop table
            cur.execute("SELECT COUNT(*) FROM stop;")
            row = cur.fetchone()
            result["stop_count"] = row[0] if row else 0

        conn.close()

        logger.info(
            "db_startup_check_passed",
            pg_trgm=result["pg_trgm"],
            postgis=result["postgis"],
            stop_count=result["stop_count"],
        )

    except Exception as e:
        result["error"] = str(e)
        logger.error("db_startup_check_failed", error=str(e))

    return result


def _check_routing_engine() -> Dict[str, Any]:
    """
    Check routing engine reachability on startup.
    Uses RoutingTool.health_check() which hits GET /api/health.
    """
    result = {"reachable": False, "url": settings.routing.engine_url}
    try:
        from controller.tools.routing_tool import RoutingTool
        tool = RoutingTool()
        result["reachable"] = tool.health_check()
        logger.info(
            "routing_engine_startup_check",
            reachable=result["reachable"],
            url=result["url"],
        )
    except Exception as e:
        result["error"] = str(e)
        logger.warning("routing_engine_startup_check_failed", error=str(e))
    return result


def _check_fare_model() -> Dict[str, Any]:
    """
    Check fare model availability on startup.
    Tries to load TripPricePredictor — logs coefficients if successful.
    """
    result = {
        "available":    False,
        "source":       settings.fare.model_source,
        "coefficients": None,
    }
    try:
        from model.fare.price_predictor import TripPricePredictor
        predictor = TripPricePredictor()
        result["available"]    = True
        result["coefficients"] = predictor.coefficients
        logger.info(
            "fare_model_startup_check_passed",
            source=result["source"],
            coefficients=result["coefficients"],
        )
    except Exception as e:
        result["error"] = str(e)
        logger.warning(
            "fare_model_startup_check_failed",
            error=str(e),
            source=result["source"],
        )
    return result

 
# Agent singleton 

# Loaded once at startup — shared across all requests
_agent = None


def _get_agent():
    """Return the singleton TransportAgent."""
    global _agent
    if _agent is None:
        raise RuntimeError("Agent not initialized — startup failed")
    return _agent


 
# Lifespan (startup + shutdown) 

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.
    Runs startup checks then initializes agent.
    """
    global _agent

    _setup_logging()

    logger.info("=" * 55)
    logger.info("TRANSPORT AGENT STARTING UP")
    logger.info("=" * 55)
    logger.info(settings.summary())

    # Startup checks 
    db_status      = _check_database()
    routing_status = _check_routing_engine()
    fare_status    = _check_fare_model()

    # Hard fail: DB must be reachable  
    if not db_status["connected"]:
        logger.error(
            "STARTUP FAILED: Database unreachable",
            error=db_status.get("error"),
            dsn=f"{settings.db.host}:{settings.db.port}/{settings.db.db}",
        )
        raise RuntimeError(
            f"Cannot connect to PostgreSQL: {db_status.get('error')}"
        )

    #  Warn: pg_trgm / PostGIS missing but don't hard fail 
    if not db_status["pg_trgm"]:
        logger.warning(
            "pg_trgm extension not found — geo fuzzy search will fail",
            fix="Run: CREATE EXTENSION pg_trgm;",
        )
    if not db_status["postgis"]:
        logger.warning(
            "PostGIS extension not found — coordinate queries will fail",
            fix="Run: CREATE EXTENSION postgis;",
        )

    #  Warn: routing engine unreachable 
    if not routing_status["reachable"]:
        logger.warning(
            "Routing engine unreachable at startup",
            url=routing_status["url"],
            note="Journey requests will fail until engine is reachable",
        )

    #  Warn: fare model missing 
    if not fare_status["available"]:
        logger.warning(
            "Fare model not available",
            source=fare_status["source"],
            note="Fare estimates will use route.cost baseline only",
        )

    #  Initialize agent 
    try:
        from controller.agent import TransportAgent
        _agent = TransportAgent()
        logger.info("agent_ready")
    except Exception as e:
        logger.error("STARTUP FAILED: Agent initialization error", error=str(e))
        raise

    logger.info("TRANSPORT AGENT READY")
    logger.info("=" * 55)

    #  App runs here 
    yield

    #  Shutdown 
    logger.info("transport_agent_shutting_down")
    _agent = None


 
# FastAPI app
 


app = FastAPI(
    title="Transport Agent API",
    description=(
        "AI-powered Alexandria public transport assistant. "
        "Supports Arabic and English."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_development else None,   # hide docs in prod
    redoc_url=None,
)

#  CORS — allow Streamlit frontend 
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",   # Streamlit default port
        "http://127.0.0.1:8501",
        f"http://localhost:{settings.app_port}",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)



# Request timing middleware



@app.middleware("http")
async def add_request_timing(request: Request, call_next):
    """Log request timing for every call."""
    start      = time.time()
    request_id = str(uuid.uuid4())[:8]

    structlog.contextvars.bind_contextvars(request_id=request_id)

    response = await call_next(request)

    elapsed_ms = round((time.time() - start) * 1000, 2)
    logger.info(
        "request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        elapsed_ms=elapsed_ms,
        request_id=request_id,
    )

    structlog.contextvars.clear_contextvars()
    return response



# Endpoints



@app.get("/", tags=["info"])
async def root():
    """Basic info endpoint."""
    return {
        "service":     "Transport Agent",
        "version":     "1.0.0",
        "description": "Alexandria public transport AI assistant",
        "endpoints": {
            "chat":           "POST /chat",
            "health":         "GET  /health",
            "clear_session":  "GET  /session/{session_id}/clear",
            "docs":           "GET  /docs  (development only)",
        },
    }


@app.post(
    "/chat",
    response_model=AgentResponse,
    tags=["chat"],
    summary="Send a message to the transport agent",
)
async def chat(request: ChatRequest) -> AgentResponse:
    """
    Main chat endpoint.

    Accepts:
      {
        "message":    "عايز أروح من العصافرة لسيدي بشر",
        "session_id": "user-123",
        "language_hint": "ar"   (optional)
      }

    Returns:
      AgentResponse with text + journeys + metadata
    """
    agent = _get_agent()

    logger.info(
        "chat_request",
        session_id=request.session_id,
        message_len=len(request.message),
        language_hint=request.language_hint,
    )

    response: AgentResponse = agent.handle(
        user_input=request.message,
        session_id=request.session_id,
    )

    return response


@app.get(
    "/health",
    tags=["ops"],
    summary="System health check",
)
async def health() -> Dict[str, Any]:
    """
    Check health of all system components.

    Returns status of:
      - API itself
      - PostgreSQL connection
      - Routing engine
      - Fare model
      - Active sessions count
    """
    from model.memory.conversation import get_session_store

    #  DB check 
    db_status = _check_database()

    #  Routing engine check 
    routing_status = _check_routing_engine()

    #  Fare model check 
    fare_status = _check_fare_model()

    #  Session count 
    try:
        store = get_session_store()
        session_count = store.active_session_count
    except Exception:
        session_count = -1

    overall_ok = db_status["connected"] and db_status["pg_trgm"] and db_status["postgis"]

    return {
        "status":   "ok" if overall_ok else "degraded",
        "database": {
            "connected":  db_status["connected"],
            "pg_trgm":    db_status["pg_trgm"],
            "postgis":    db_status["postgis"],
            "stop_count": db_status["stop_count"],
            "error":      db_status.get("error"),
        },
        "routing_engine": {
            "reachable": routing_status["reachable"],
            "url":       routing_status["url"],
        },
        "fare_model": {
            "available": fare_status["available"],
            "source":    fare_status["source"],
        },
        "sessions": {
            "active": session_count,
        },
        "config": {
            "env":        settings.app_env,
            "model":      settings.model.name,
            "adapter":    settings.model.adapter_source,
        },
    }


@app.get(
    "/session/{session_id}/clear",
    tags=["session"],
    summary="Clear session memory",
)
async def clear_session(session_id: str) -> Dict[str, Any]:
    """
    Clear conversation memory for a session.
    Called when user starts a new conversation explicitly.
    """
    from model.memory.conversation import get_session_store

    store = get_session_store()
    store.delete(session_id)

    logger.info("session_cleared_via_api", session_id=session_id)

    return {
        "status":     "cleared",
        "session_id": session_id,
    }


 
# Error handlers



@app.exception_handler(Exception)
async def global_exception_handler(
    request: Request,
    exc:     Exception,
) -> JSONResponse:
    """
    Catch-all exception handler.
    Returns AgentResponse-shaped error so Streamlit can handle it.
    """
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "text":     "حدث خطأ غير متوقع. حاول مرة تانية.",
            "language": "ar",
            "journeys": [],
            "error":    str(exc),
        },
    )


# 
# Entry point
# 


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.app_port,
        reload=settings.is_development,    # auto-reload in dev mode
        log_level=settings.log_level.lower(),
        workers=1,                          # single worker — agent is stateful
    )