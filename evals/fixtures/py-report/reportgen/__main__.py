import sys

from .report import build_report


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m reportgen <events.csv> [lookup.json]", file=sys.stderr)
        return 2
    lookup = argv[1] if len(argv) > 1 else "data/regions.json"
    sys.stdout.write(build_report(argv[0], lookup))
    return 0


if __name__ == "__main__":
    sys.exit(main())
