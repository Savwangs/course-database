"""Table 1: courses_catalog – Static course data scraped from the DVC catalog."""

from backend.models import db


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
