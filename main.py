"""Run ContentPilot from any working directory."""

import argparse
import os
import sys
from core import config
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="ContentPilot editorial workspace")
    parser.add_argument("--host", default=os.getenv("CONTENT_AGENT_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("CONTENT_AGENT_PORT", "8000"))
    )
    parser.add_argument(
        "--reload", action="store_true", help="Enable development reload"
    )
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not config.API_KEY:
        parser.error("Set CONTENTPILOT_API_KEY before binding to a network interface")
    os.environ["CONTENT_AGENT_HOST"] = args.host
    print(f"ContentPilot: http://{args.host}:{args.port}")
    uvicorn.run("api.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
