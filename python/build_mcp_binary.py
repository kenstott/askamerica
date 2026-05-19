#!/usr/bin/env python3
"""
Build the askamerica-mcp standalone binary using PyInstaller.

The binary acts as an installer (GUI) when run interactively,
and as an MCP server (stdio) when launched by Claude Desktop.

Usage:
    pip install pyinstaller jdk4py jpype1 mcp
    python build_mcp_binary.py

Output: dist/askamerica-mcp  (or dist/askamerica-mcp.exe on Windows)
"""
import platform
import subprocess
import sys
from pathlib import Path


def main():
    here = Path(__file__).parent
    system = platform.system()
    sep = ";" if system == "Windows" else ":"

    try:
        from jdk4py import JAVA_HOME
    except ImportError:
        sys.exit("jdk4py not installed. Run: pip install jdk4py")

    try:
        import jpype
        jpype_dir = Path(jpype.__file__).parent
    except ImportError:
        sys.exit("jpype1 not installed. Run: pip install jpype1")

    entry = here / "askamerica" / "main.py"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "askamerica-mcp",
        # macOS/Windows: no terminal window on double-click (produces .app / windowed .exe)
        # Linux: keep console so MCP stdio works reliably
        "--windowed" if system in ("Darwin", "Windows") else "--console",
        # Bundle the jdk4py JDK
        "--add-data", f"{JAVA_HOME}{sep}jdk4py/java-runtime",
        # Bundle JPype native libs
        "--add-data", f"{jpype_dir}{sep}jpype",
        "--hidden-import", "askamerica.engine",
        "--hidden-import", "askamerica.config",
        "--hidden-import", "askamerica.exceptions",
        "--hidden-import", "askamerica.installer",
        "--hidden-import", "askamerica.mcp_server",
        "--hidden-import", "jpype",
        "--hidden-import", "jpype._jpype",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.ttk",
        "--hidden-import", "tkinter.font",
        "--hidden-import", "mcp.server",
        "--hidden-import", "mcp.server.stdio",
        "--hidden-import", "mcp.server.models",
        "--hidden-import", "mcp.types",
        "--hidden-import", "anyio",
        "--hidden-import", "anyio._backends._asyncio",
        "--hidden-import", "anyio._backends._trio",
        str(entry),
    ]

    print(f"Building askamerica-mcp for {system}…")
    subprocess.run(cmd, check=True, cwd=here)

    out = here / "dist" / ("askamerica-mcp.exe" if system == "Windows" else "askamerica-mcp")
    print(f"\nBinary ready: {out}")
    print("\nUser workflow:")
    print("  1. Download the binary")
    print("  2. Double-click → installer UI appears")
    print("  3. Enter API key → click Install")
    print("  4. Restart Claude Desktop")


if __name__ == "__main__":
    main()
