"""
Root-level CLI shim — maps simple subcommands used by cron and Docker CMD.

    python main.py run        # full top-of-funnel (prospect → close monitoring)
    python main.py followup   # process due follow-up sequences only
    python main.py report     # weekly sales report
    python main.py <anything> # passed straight through to the orchestrator

Equivalent to running python -m src.orchestrator with the appropriate --step flag.
"""
import sys

_MAP = {
    "run": ["--step", "all"],
    "followup": ["--step", "followup"],
    "report": ["--step", "report"],
}


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in _MAP:
        sys.argv = [sys.argv[0]] + _MAP[args[0]] + args[1:]
    from src.orchestrator import main as _main
    _main()


if __name__ == "__main__":
    main()
