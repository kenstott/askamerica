"""
Unified entry point for the askamerica-mcp binary.

  Interactive (double-click / terminal with tty): show installer UI
  Piped (launched by Claude Desktop via stdio):   run MCP server
"""
import sys


def main():
    if sys.stdin.isatty():
        from askamerica.installer import run_installer
        run_installer()
    else:
        from askamerica.mcp_server import mcp
        mcp.run()


if __name__ == "__main__":
    main()
