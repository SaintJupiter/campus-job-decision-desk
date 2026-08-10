from __future__ import annotations

import argparse
import hashlib
import json

from campus_job_desk.database import ENGINE, SessionLocal, create_schema
from campus_job_desk.domain.enums import SourceKind
from campus_job_desk.ingest.adapters import parse_snapshot
from campus_job_desk.repositories.imports import import_parsed_snapshot
from campus_job_desk.services.materialization import materialize_batch


def main() -> None:
    parser = argparse.ArgumentParser(description="导入一份用户自带的岗位表")
    parser.add_argument("path")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--independence-group", required=True)
    parser.add_argument(
        "--source-kind",
        choices=[item.value for item in SourceKind],
        default=SourceKind.PAID_TABLE.value,
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="仅导入前 N 条记录，用于真实数据的轻量验收；不会修改原文件",
    )
    args = parser.parse_args()

    snapshot = parse_snapshot(
        args.path,
        source_name=args.source_name,
        source_kind=SourceKind(args.source_kind),
    )
    if args.limit is not None:
        if args.limit <= 0:
            raise SystemExit("--limit 必须大于 0")
        limited_rows = snapshot.rows[: args.limit]
        sample_hash = hashlib.sha256(
            f"{snapshot.file_hash}:sample:{args.limit}".encode()
        ).hexdigest()
        snapshot = snapshot.model_copy(
            update={
                "file_hash": sample_hash,
                "rows": limited_rows,
                "rejected_rows": [
                    item
                    for item in snapshot.rejected_rows
                    if int(item.get("row_number", item.get("line_number", 0)))
                    <= args.limit
                ],
            }
        )
    create_schema(ENGINE)
    with SessionLocal() as session:
        result = import_parsed_snapshot(
            session,
            snapshot,
            source_id=args.source_id,
            independence_group=args.independence_group,
        )
        materialized = materialize_batch(session, result.batch_id)
    print(
        json.dumps(
            {"import": result.__dict__, "materialization": materialized.__dict__},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
