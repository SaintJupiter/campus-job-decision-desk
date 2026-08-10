from __future__ import annotations

from pathlib import Path


def main() -> None:
    """Reset only the repository's exact generated public-demo SQLite files."""

    repository = Path(__file__).resolve().parents[1]
    database = repository / "data" / "demo" / "public-demo.sqlite"
    targets = (
        database,
        database.with_name(database.name + "-wal"),
        database.with_name(database.name + "-shm"),
    )
    for target in targets:
        if target.parent != repository / "data" / "demo":
            raise RuntimeError("refusing to reset a path outside data/demo")
        target.unlink(missing_ok=True)
    print(f"reset exact synthetic demo database: {database.relative_to(repository)}")


if __name__ == "__main__":
    main()
