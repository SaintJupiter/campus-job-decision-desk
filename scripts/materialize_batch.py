from __future__ import annotations

import argparse
import json

from campus_job_desk.database import ENGINE, SessionLocal, create_schema
from campus_job_desk.services.materialization import materialize_batch


def main() -> None:
    parser = argparse.ArgumentParser(description="将不可变原始批次物化为可审查的机会与字段证据")
    parser.add_argument("batch_id")
    args = parser.parse_args()
    create_schema(ENGINE)
    with SessionLocal() as session:
        result = materialize_batch(session, args.batch_id)
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
