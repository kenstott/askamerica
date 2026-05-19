"""
Unified entry point for the askamerica-mcp binary.

  --mcp flag (set in Claude Desktop config): run MCP server over stdio
  No flag (double-click .app / .exe):        show installer UI
"""
import sys


def main():
    if "--mcp" in sys.argv:
        from askamerica.mcp_server import mcp
        mcp.run()
    else:
        from askamerica.installer import run_installer
        run_installer()


if __name__ == "__main__":
    main()
