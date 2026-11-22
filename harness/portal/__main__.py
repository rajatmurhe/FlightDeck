"""python -m harness.portal --db <path> --port 8000 [--flags <path>]"""
import argparse

import uvicorn

from harness.portal.app import create_app


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m harness.portal")
    ap.add_argument("--db", required=True)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--flags", default=None, help="fault-flag JSON (never given to FlightDeck)")
    args = ap.parse_args(argv)
    uvicorn.run(create_app(args.db, args.flags), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
