"""
DVC Course Assistant – Flask Web App (thin controller).

All business logic lives in:
  * backend.services.search_service.CourseSearcher
  * backend.services.transfer_service.TransferAssistant

All data models live in:
  * backend.models.course.CoursesCatalog
  * backend.models.interaction_log.InteractionLog
"""

import os
import json
import secrets
import traceback
from pathlib import Path
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from openai import APITimeoutError, APIConnectionError, RateLimitError
from backend.models.interaction_log import InteractionLog

from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI
from dotenv import load_dotenv

from backend.models import db, init_db
from backend.services.search_service import CourseSearcher
from backend.services.transfer_service import TransferAssistant
from backend import guardrails as input_guardrails

# ---------------------------------------------------------------------------
#  Environment & clients
# ---------------------------------------------------------------------------
load_dotenv()
if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("OPENAI_API_KEY is not set.")
openai_client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=20.0,
    max_retries=2
)

# ---------------------------------------------------------------------------
#  Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
)
MAX_PROMPT_CHARS = int(os.getenv("MAX_PROMPT_CHARS", "2000"))
MIN_QUERY_CHARS = int(os.getenv("MIN_QUERY_CHARS", "3"))
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))  # 10 exchanges

# SQLAlchemy configuration
# Default to a local SQLite DB; set DATABASE_URL for Cloud SQL / Postgres in production
db_url = os.getenv("DATABASE_URL", "sqlite:///courses.db")

# Heroku-style URLs sometimes use "postgres://", but SQLAlchemy expects "postgresql://"
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize the database (creates tables if they don't exist)
init_db(app)

''' Will cause errors
# ---------------------------------------------------------------------------
#  Load course data
# ---------------------------------------------------------------------------
db_path = Path(__file__).parent.parent / "dvc_scraper" / "Full_STEM_DataBase.json"

if not db_path.exists():
    raise FileNotFoundError(f"Could not find database at: {db_path}")

with open(db_path, "r", encoding="utf-8") as f:
    course_data = json.load(f)

print(f"Loaded {len(course_data)} courses from {db_path}")
'''


# ---------------------------------------------------------------------------
#  Instantiate services
# ---------------------------------------------------------------------------
searcher = CourseSearcher(openai_client)

transfer = TransferAssistant(
    openai_client,
    log_callback=lambda q, p, r: searcher.log_interaction(q, p, r),
)

def error_response(code: str, message: str, http_status: int = 400, *, meta: dict | None = None):
    payload = {"success": False, "error": {"code": code, "message": message}}
    if meta:
        payload["error"]["meta"] = meta
    return jsonify(payload), http_status


def validate_ask_request(req):
    # Require JSON
    if not req.is_json:
        return None, error_response("INVALID_CONTENT_TYPE", "Request must be application/json.", 415)

    data = req.get_json(silent=True)
    if not isinstance(data, dict):
        return None, error_response("INVALID_JSON", "Invalid JSON body.", 400)

    if "query" not in data:
        return None, error_response("MISSING_FIELD", "Missing required field: query", 400)

    q = data.get("query")
    if not isinstance(q, str):
        return None, error_response("INVALID_FIELD_TYPE", "Field 'query' must be a string.", 400)

    q = q.strip()
    if not q:
        return None, error_response("EMPTY_QUERY", "Query cannot be empty.", 400)

    if len(q) < MIN_QUERY_CHARS:
        return None, error_response(
            "QUERY_TOO_SHORT",
            f"Query must be at least {MIN_QUERY_CHARS} characters.",
            400,
            meta={"min_chars": MIN_QUERY_CHARS, "actual_chars": len(q)}
        )

    if len(q) > MAX_PROMPT_CHARS:
        return None, error_response(
            "QUERY_TOO_LONG",
            f"Query is too long. Max is {MAX_PROMPT_CHARS} characters.",
            413,
            meta={"max_chars": MAX_PROMPT_CHARS, "actual_chars": len(q)}
        )

    return q, None


def log_guardrail(user_prompt: str, guardrail_type: str, reason: str, http_status: int, meta: dict | None = None):
    # Keep it compatible with your existing log_interaction signature
    parsed_data = {
        "guardrail_triggered": True,
        "guardrail_type": guardrail_type,
        "reason": reason,
        "http_status": http_status,
    }
    if meta:
        parsed_data["meta"] = meta
    searcher.log_interaction(user_prompt, parsed_data, f"[GUARDRAIL] {guardrail_type}: {reason}", status="guardrail")

def require_admin(req) -> bool:
    expected = os.getenv("ADMIN_TOKEN")
    return bool(expected) and req.headers.get("X-Admin-Token") == expected
# ---------------------------------------------------------------------------
#  Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the landing page."""
    return render_template("landing.html")


@app.route("/chatbot")
def chatbot():
    """Serve the chatbot interface."""
    return render_template("chatbot.html")


@app.route("/ask", methods=["POST"])
@limiter.limit("10 per minute")  # Rate limit guardrail
def ask():
    """
    API endpoint to handle user queries with conversation memory.

    Expects JSON: {"query": "user question here"}
    Returns JSON: {"response": "formatted answer", "success": true/false}
    """
    try:
        # -----------------------------
        # Input Guardrails
        # -----------------------------

        if not request.is_json:
            log_guardrail("<invalid_request>", "input", "INVALID_CONTENT_TYPE", 415)
            return error_response(
                "INVALID_CONTENT_TYPE",
                "Request must be application/json.",
                415
            )

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            log_guardrail("<invalid_request>", "input", "INVALID_JSON", 400)
            return error_response("INVALID_JSON", "Invalid JSON body.", 400)

        if "query" not in data:
            log_guardrail("<invalid_request>", "input", "MISSING_FIELD", 400)
            return error_response("MISSING_FIELD", "Missing required field: query", 400)

        user_query = data["query"]

        if not isinstance(user_query, str):
            log_guardrail("<invalid_request>", "input", "INVALID_FIELD_TYPE", 400)
            return error_response(
                "INVALID_FIELD_TYPE",
                "Field 'query' must be a string.",
                400
            )

        user_query = user_query.strip()

        if not user_query:
            log_guardrail("<invalid_request>", "input", "EMPTY_QUERY", 400)
            return error_response("EMPTY_QUERY", "Query cannot be empty.", 400)

        if len(user_query) < MIN_QUERY_CHARS:
            log_guardrail(
                user_query,
                "input",
                "QUERY_TOO_SHORT",
                400,
                {"min_chars": MIN_QUERY_CHARS, "actual_chars": len(user_query)}
            )
            return error_response(
                "QUERY_TOO_SHORT",
                f"Query must be at least {MIN_QUERY_CHARS} characters.",
                400,
                meta={"min_chars": MIN_QUERY_CHARS, "actual_chars": len(user_query)}
            )

        code, msg = input_guardrails.check_profanity(user_query)
        if code:
            log_guardrail(user_query, "input", code, 400)
            return error_response(code, msg, 400)

        code, msg = input_guardrails.check_pii(user_query)
        if code:
            log_guardrail(user_query, "input", code, 400)
            return error_response(code, msg, 400)

        code, msg = input_guardrails.check_prompt_injection(user_query)
        if code:
            log_guardrail(user_query, "input", code, 400)
            return error_response(code, msg, 400)

        code, msg = input_guardrails.check_off_topic(user_query)
        if code:
            log_guardrail(user_query, "input", code, 400)
            return error_response(code, msg, 400)

        code, msg = input_guardrails.check_language(user_query)
        if code:
            log_guardrail(user_query, "input", code, 400)
            return error_response(code, msg, 400)

        if len(user_query) > MAX_PROMPT_CHARS:
            log_guardrail(
                user_query,
                "input",
                "QUERY_TOO_LONG",
                413,
                {"max_chars": MAX_PROMPT_CHARS, "actual_chars": len(user_query)}
            )
            return error_response(
                "QUERY_TOO_LONG",
                f"Query exceeds maximum length of {MAX_PROMPT_CHARS} characters.",
                413
            )

        # -----------------------------
        # Session / Conversation Memory
        # -----------------------------

        if "conversation_history" not in session:
            session["conversation_history"] = []

        conversation_history = session["conversation_history"]

        # -----------------------------
        # Call Service Layer (LLM call)
        # -----------------------------

        try:
            response = searcher.ask(
                user_query,
                conversation_history=conversation_history,
                enable_logging=True,
                transfer_handler=transfer.maybe_handle,
            )

        except (APITimeoutError, APIConnectionError) as e:
            # OpenAI request timed out or network failed
            log_guardrail(
                user_query,
                "timeout",
                "OPENAI_TIMEOUT",
                504,
                {"error": str(e)}
            )
            return error_response(
                "UPSTREAM_TIMEOUT",
                "The assistant timed out. Please try again.",
                504
            )
        except RateLimitError as e:
            # OpenAI upstream rate limit (NOT your Flask limiter)
            log_guardrail(
                user_query,
                "upstream_rate_limit",
                "OPENAI_RATE_LIMIT",
                503,
                {"error": str(e)}
            )
            return error_response(
                "UPSTREAM_RATE_LIMIT",
                "Upstream rate limit reached. Please try again shortly.",
                503
            )

        # -----------------------------
        # Output Guardrail: Empty Response
        # -----------------------------

        if not response or not isinstance(response, str):
            log_guardrail(user_query, "output", "EMPTY_RESPONSE", 500)
            return error_response(
                "INVALID_RESPONSE",
                "The assistant returned an invalid response.",
                500
            )

        # -----------------------------
        # Update Conversation History
        # -----------------------------

        conversation_history.append({"role": "user", "content": user_query})
        conversation_history.append({"role": "assistant", "content": response})

        if len(conversation_history) > MAX_HISTORY_MESSAGES:
            conversation_history = conversation_history[-MAX_HISTORY_MESSAGES:]

        session["conversation_history"] = conversation_history
        session.modified = True

        # -----------------------------
        # Success Response
        # -----------------------------

        return jsonify({
            "success": True,
            "response": response,
            "message_count": len(conversation_history),
        })

    except Exception as e:
        print(f"Error in /ask route: {e}")
        traceback.print_exc()

        log_guardrail(
            "<server_error>",
            "server",
            "UNHANDLED_EXCEPTION",
            500,
            {"error": str(e)}
        )

        return error_response(
            "SERVER_ERROR",
            "An error occurred processing your request.",
            500
        )


@app.route("/clear", methods=["POST"])
def clear_conversation():
    """Clear the conversation history and start fresh."""
    try:
        session["conversation_history"] = []
        session.modified = True
        return jsonify({"success": True, "message": "Conversation history cleared"})
    except Exception as e:
        print(f"Error in /clear route: {e}")
        return jsonify({"success": False, "error": "Failed to clear conversation"}), 500


@app.route("/conversation/status", methods=["GET"])
def conversation_status():
    """Get the current conversation status."""
    try:
        history = session.get("conversation_history", [])
        return jsonify({
            "success": True,
            "message_count": len(history),
            "has_history": len(history) > 0,
            "exchange_count": len(history) // 2,
        })
    except Exception as e:
        print(f"Error in /conversation/status route: {e}")
        return jsonify({"success": False, "error": "Failed to get conversation status"}), 500


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "database": app.config["SQLALCHEMY_DATABASE_URI"].split("://")[0],
        "service": "coursegenie"
    })


@app.route("/logs", methods=["GET"])
@limiter.limit("10 per minute")
def view_logs():
    """View interaction logs from the database.

    Query parameters:
        limit – Number of logs to retrieve (default 50, max 500)
        skip  – Number of logs to skip for pagination (default 0)
    """
    if not require_admin(request):
        log_guardrail("<logs>", "security", "UNAUTHORIZED_LOG_ACCESS", 403)
        return error_response("FORBIDDEN", "Not authorized.", 403)

    try:
        limit = min(request.args.get("limit", 50, type=int), 500)
        skip = max(request.args.get("skip", 0, type=int), 0)

        query = (
            InteractionLog.query
            .order_by(InteractionLog.timestamp.desc())
            .offset(skip)
            .limit(limit)
        )
        logs = [log.to_dict() for log in query.all()]
        total_count = InteractionLog.query.count()

        return jsonify({
            "success": True,
            "count": len(logs),
            "total": total_count,
            "source": "database",
            "logs": logs,
        })

    except Exception as e:
        print(f"Error in /logs route: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.errorhandler(429)
def ratelimit_handler(e):
    try:
        log_guardrail(
            "<rate_limited>",
            "rate_limit",
            "TOO_MANY_REQUESTS",
            429,
            {"detail": str(e)}
        )
    except Exception:
        pass

    return error_response(
        "RATE_LIMITED",
        "Too many requests. Please slow down.",
        429
    )

# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    host = "0.0.0.0"
    debug = os.environ.get("FLASK_ENV") != "production"

    print("\n" + "=" * 80)
    print("DVC Course Assistant – Flask Web App")
    print("=" * 80)
    print(f"Database: {app.config['SQLALCHEMY_DATABASE_URI']}")
    print(f"Starting server at http://{host}:{port}")
    print(f"Debug mode: {debug}")
    print("=" * 80 + "\n")

    app.run(debug=debug, host=host, port=port)
