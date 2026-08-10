from __future__ import annotations

import argparse
from pathlib import Path

from campus_job_desk.evaluation import EvaluationHarness, write_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run synthetic contract/heuristic fixtures, aggregate-only database checks, "
            "and local API timing observations."
        )
    )
    parser.add_argument(
        "--database-url",
        default="sqlite:///data/private/campus-job-desk-app.sqlite",
        help="SQLAlchemy database URL to inspect without modifying it.",
    )
    parser.add_argument(
        "--database-label",
        default="private-baseline",
        help="Non-sensitive label included in the report; the database path is not emitted.",
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path("evaluation/fixtures/gold.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evaluation/results"),
    )
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    harness = EvaluationHarness.from_database_url(
        args.database_url,
        database_label=args.database_label,
        fixture_path=args.fixtures,
    )
    try:
        report = harness.run(
            performance_samples=args.samples,
            performance_warmups=args.warmups,
        )
    finally:
        harness.close()
    json_path = args.output_dir / "latest.json"
    markdown_path = args.output_dir / "latest.md"
    write_report(report, json_path=json_path, markdown_path=markdown_path)
    contract = report["fixture_summary"]["contract_boundary"]
    heuristic = report["fixture_summary"]["heuristic_sample"]
    print(
        f"contract={contract['passed']}/{contract['total']} "
        f"heuristic={heuristic['passed']}/{heuristic['total']} "
        f"json={json_path} markdown={markdown_path}"
    )
    if contract["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
