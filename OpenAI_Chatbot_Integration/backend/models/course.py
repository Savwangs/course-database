"""Tables: courses_catalog (static catalog), course_sections (section/availability data)."""

from backend.models import db


class CourseSection(db.Model):
    """Section-level data (schedule, instructor, availability). Used by search/parser allow-lists."""
    __tablename__ = "course_sections"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    course_code = db.Column(db.String(20), nullable=False, index=True)
    section_number = db.Column(db.String(20), nullable=True)
    instructor = db.Column(db.String(100), nullable=True)
    schedule = db.Column(db.String(100), nullable=True)  # e.g. "MW 10:00-11:00" or "Asynchronous"
    modality = db.Column(db.String(50), nullable=True)   # in-person, online, hybrid
    seat_availability = db.Column(db.String(20), nullable=True)
    units = db.Column(db.String(10), nullable=True)


class CoursesCatalog(db.Model):
    __tablename__ = "courses_catalog"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    course_code = db.Column(db.String(20), nullable=False, unique=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    units = db.Column(db.String(10), nullable=True)
    description = db.Column(db.Text, nullable=True)
    prerequisites = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<CoursesCatalog {self.course_code}: {self.title}>"

    def to_dict(self):
        return {
            "id": self.id,
            "course_code": self.course_code,
            "title": self.title,
            "units": self.units,
            "description": self.description,
            "prerequisites": self.prerequisites,
        }
