from datetime import datetime, timezone
from backend.models import db

class InteractionLog(db.Model):
    __tablename__ = "interaction_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    timestamp = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Existing columns in your SQLite table (based on .schema)
    user_query = db.Column(db.Text, nullable=False)
    parsed_data = db.Column(db.Text, nullable=True)     # store JSON as TEXT in SQLite
    ai_response = db.Column(db.Text, nullable=True)
    latency_ms = db.Column(db.Integer, nullable=True)

    # New “Week 5 guardrail” fields (we’ll add these columns to SQLite next)
    project_name = db.Column(db.Text, nullable=True)
    user_prompt = db.Column(db.Text, nullable=True)
    chatbot_response_summary = db.Column(db.Text, nullable=True)
    status = db.Column(db.Text, nullable=True)
    confidence_level = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,

            "user_query": self.user_query,
            "parsed_data": self.parsed_data,
            "ai_response": self.ai_response,
            "latency_ms": self.latency_ms,

            "project_name": self.project_name,
            "user_prompt": self.user_prompt,
            "chatbot_response_summary": self.chatbot_response_summary,
            "status": self.status,
            "confidence_level": self.confidence_level,
        }