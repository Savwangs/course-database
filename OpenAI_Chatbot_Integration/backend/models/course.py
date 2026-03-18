"""Tables: courses_catalog (static catalog), course_sections (section/availability data)."""

import os
from backend.models import db
from sqlalchemy.dialects.postgresql import JSONB


class CourseSection(db.Model):
    __tablename__ = os.getenv("COURSE_SECTIONS_TABLE", "course_sections_fall_2026")

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    course_code = db.Column(db.String(32), nullable=False, index=True)
    section_number = db.Column(db.String(16), nullable=True)
    instructor = db.Column(db.Text, nullable=True)
    schedule = db.Column(JSONB, nullable=True)
    modality = db.Column(db.String(16), nullable=True)
    seat_availability = db.Column(db.String(40), nullable=True)
    units = db.Column(db.String(16), nullable=True)
    comments = db.Column(db.Text, nullable=True)
    prereq = db.Column(db.Text, nullable=True)
    advisory = db.Column(db.Text, nullable=True)


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