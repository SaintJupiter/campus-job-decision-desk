from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from campus_job_desk.ingest import read_markdown_snapshot  # noqa: E402
from campus_job_desk.storage import connect, database_summary, import_snapshot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot")
    parser.add_argument("--db", default="data/private/campus-job-desk.sqlite")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-name", required=True)
    args = parser.parse_args()

    snapshot = read_markdown_snapshot(args.snapshot)
    connection = connect(ROOT / args.db)
    try:
        result = import_snapshot(
            connection,
            snapshot,
            source_id=args.source_id,
            source_name=args.source_name,
        )
        print(json.dumps({"import": result, "database": database_summary(connection)}, ensure_ascii=False, indent=2))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
