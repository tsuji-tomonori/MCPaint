import argparse


def main():
    parser = argparse.ArgumentParser(description="MCPaint local paint studio")
    parser.add_argument("--mcp", action="store_true", help="Run stdio MCP bridge")
    parser.add_argument("--self-test", action="store_true", help="Run packaged runtime smoke test")
    args = parser.parse_args()
    if args.self_test:
        from .selftest import run

        return run()
    if args.mcp:
        from .mcp_server import run_mcp

        run_mcp()
        return 0
    from .app import run_app

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
