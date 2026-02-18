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

from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI
from dotenv import load_dotenv

from backend.models import db, init_db
from backend.services.search_service import CourseSearcher
from backend.services.transfer_service import TransferAssistant

# ---------------------------------------------------------------------------
#  Environment & clients
# ---------------------------------------------------------------------------
load_dotenv()
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------------------------------------------------------
#  Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))

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

# ---------------------------------------------------------------------------
#  Load course data
# ---------------------------------------------------------------------------
db_path = Path(__file__).parent.parent / "dvc_scraper" / "Full_STEM_DataBase.json"

if not db_path.exists():
    raise FileNotFoundError(f"Could not find database at: {db_path}")

with open(db_path, "r", encoding="utf-8") as f:
    course_data = json.load(f)

print(f"Loaded {len(course_data)} courses from {db_path}")

# ---------------------------------------------------------------------------
#  Instantiate services
# ---------------------------------------------------------------------------
searcher = CourseSearcher(course_data, openai_client)

transfer = TransferAssistant(
    openai_client,
    log_callback=lambda q, p, r: searcher.log_interaction(q, p, r),
)

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
def ask():
    """API endpoint to handle user queries with conversation memory.

    Expects JSON: {"query": "user question here"}
    Returns JSON: {"response": "formatted answer", "success": true/false}
    """
    try:
        data = request.get_json()

        if not data or "query" not in data:
            return jsonify({"success": False, "error": "No query provided"}), 400

        user_query = data["query"].strip()
        if not user_query:
            return jsonify({"success": False, "error": "Empty query"}), 400

        # Initialize conversation history in session if not exists
        if "conversation_history" not in session:
            session["conversation_history"] = []

        conversation_history = session["conversation_history"]

        # Delegate to service layer
        response = searcher.ask(
            user_query,
            conversation_history=conversation_history,
            enable_logging=True,
            transfer_handler=transfer.maybe_handle,
        )

        # Update conversation history
        conversation_history.append({"role": "user", "content": user_query})
        conversation_history.append({"role": "assistant", "content": response})

        # Keep only last 20 messages (10 exchanges)
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]

        session["conversation_history"] = conversation_history
        session.modified = True

        return jsonify({
            "success": True,
            "response": response,
            "message_count": len(conversation_history),
        })

    except Exception as e:
        print(f"Error in /ask route: {e}")
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": "An error occurred processing your request",
        }), 500


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
        "courses_loaded": len(course_data),
        "database": app.config["SQLALCHEMY_DATABASE_URI"].split("://")[0],
    })


@app.route("/logs", methods=["GET"])
def view_logs():
    """View interaction logs from the database.

    Query parameters:
        limit – Number of logs to retrieve (default 50, max 500)
        skip  – Number of logs to skip for pagination (default 0)
    """
    from backend.models.interaction_log import InteractionLog

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
    print(f"Loaded {len(course_data)} courses")
    print(f"Database: {app.config['SQLALCHEMY_DATABASE_URI']}")
    print(f"Starting server at http://{host}:{port}")
    print(f"Debug mode: {debug}")
    print("=" * 80 + "\n")

    app.run(debug=debug, host=host, port=port)
