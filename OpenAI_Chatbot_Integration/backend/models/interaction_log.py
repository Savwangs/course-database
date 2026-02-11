"""Table 2: interaction_logs – Tracks every student question and the AI's answer."""

from datetime import datetime, timezone

from backend.models import db


class InteractionLog(db.Model):
    __tablename__ = "interaction_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    timestamp = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    user_query = db.Column(db.Text, nullable=False)
    parsed_data = db.Column(db.JSON, nullable=True)
    ai_response = db.Column(db.Text, nullable=True)
    latency_ms = db.Column(db.Integer, nullable=True)

    def __repr__(self):
        return f"<InteractionLog {self.id} @ {self.timestamp}>"

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "user_query": self.user_query,
            "parsed_data": self.parsed_data,
            "ai_response": self.ai_response,
            "latency_ms": self.latency_ms,
        }
