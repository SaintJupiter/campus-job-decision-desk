from __future__ import annotations

import argparse

from sqlalchemy import select

from campus_job_desk.database import ENGINE, SessionLocal, create_schema
from campus_job_desk.models import RemoteSourceConnector
from campus_job_desk.services.remote_sources import sync_feishu_connector


def main() -> int:
    parser = argparse.ArgumentParser(
        description="同步已启用的飞书远程来源；适合由 cron/定时任务每日调用"
    )
    parser.add_argument("--source-id", help="只同步一个来源")
    args = parser.parse_args()

    create_schema(ENGINE)
    failed = 0
    with SessionLocal() as session:
        query = select(RemoteSourceConnector).where(
            RemoteSourceConnector.enabled.is_(True)
        )
        if args.source_id:
            query = query.where(RemoteSourceConnector.source_id == args.source_id)
        connectors = list(session.scalars(query.order_by(RemoteSourceConnector.source_id)))
        if not connectors:
            print("没有需要同步的远程来源")
            return 0
        for connector in connectors:
            if not args.source_id and connector.schedule != "DAILY":
                continue
            try:
                outcome = sync_feishu_connector(session, connector)
                print(
                    f"{outcome.source_id}: {outcome.status}; rows={outcome.row_count}; "
                    f"+{outcome.added_count} ~{outcome.modified_count} "
                    f"-{outcome.missing_count}"
                )
            except Exception as exc:  # noqa: BLE001 - batch worker must continue other sources
                failed += 1
                print(f"{connector.source_id}: FAILED; {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
