"""Run ContentPilot from any working directory."""

import argparse
import os
import sys

try:
    from core import config
    import uvicorn
except (ImportError, ModuleNotFoundError) as exc:
    print(
        "\nContentPilot could not start because a required dependency is missing.\n"
        "\nUse the assigned environment and install the project requirements first:\n"
        "  conda activate base\n"
        "  python -m pip install -r requirements.txt\n"
        "\nIf you are using the managed workspace, open the project workspace for the assigned interpreter.\n"
        f"Original error: {type(exc).__name__}: {exc}\n"
    )
    raise SystemExit(2)


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
