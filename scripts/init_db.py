from __future__ import annotations

from campus_job_desk.database import ENGINE, create_schema

if __name__ == "__main__":
    create_schema(ENGINE)
    print("database schema ready")
