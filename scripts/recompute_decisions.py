from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from campus_job_desk.database import ENGINE, SessionLocal, create_schema
from campus_job_desk.models import Opportunity
from campus_job_desk.services.workflow import recompute_all_decisions


def main() -> None:
    parser = argparse.ArgumentParser(description="重新计算岗位的三轴决策快照")
    parser.add_argument("--limit", type=int, default=0, help="0 表示全部")
    args = parser.parse_args()
    create_schema(ENGINE)
    with SessionLocal() as session:
        query = select(Opportunity.id).order_by(Opportunity.created_at)
        if args.limit > 0:
            query = query.limit(args.limit)
        opportunity_ids = list(session.scalars(query))
        count = recompute_all_decisions(session, opportunity_ids=opportunity_ids)
    print(json.dumps({"recomputed": count}, ensure_ascii=False))


if __name__ == "__main__":
    main()
