from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_db(app):
    """Initialize the database with the Flask app."""
    db.init_app(app)

    # Import models so SQLAlchemy registers their tables before create_all()
    from backend.models.course import CoursesCatalog  # noqa: F401
    from backend.models.interaction_log import InteractionLog  # noqa: F401

    with app.app_context():
        db.create_all()
