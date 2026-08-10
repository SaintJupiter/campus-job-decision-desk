from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from logic import initial_state, reduce_state, scenarios, state_snapshot  # noqa: E402


BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def render(state, clear: bool = True) -> None:
    if clear and sys.stdout.isatty():
        print("\033[2J\033[H", end="")
    snapshot = state_snapshot(state)
    print(f"{BOLD}PROTOTYPE — 校招岗位状态模型{RESET}")
    print(f"{DIM}一次性原型；当前案例 {snapshot['scenario']['key']}/8{RESET}\n")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
    print("\n" + BOLD + "操作" + RESET)
    print("[1-8] 案例  [c] 分类  [d] 去重  [v] 核验  [e] 三轴  [a] 全部  [m] 人工结论  [r] 重置  [q] 退出")


def demo() -> None:
    for scenario in scenarios():
        state = reduce_state(initial_state(scenario), "all")
        print("=" * 88)
        render(state, clear=False)


def interactive() -> None:
    cases = {scenario.key: scenario for scenario in scenarios()}
    current = cases["1"]
    state = initial_state(current)
    action_map = {
        "c": "classify",
        "d": "deduplicate",
        "v": "verify",
        "e": "evaluate",
        "a": "all",
        "m": "manual",
    }
    while True:
        render(state)
        try:
            command = input("\n> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if command == "q":
            return
        if command in cases:
            current = cases[command]
            state = initial_state(current)
        elif command == "r":
            state = initial_state(current)
        elif command in action_map:
            state = reduce_state(state, action_map[command])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="依次运行全部边界案例")
    args = parser.parse_args()
    demo() if args.demo else interactive()


if __name__ == "__main__":
    main()
