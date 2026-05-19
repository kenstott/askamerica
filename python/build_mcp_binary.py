#!/usr/bin/env python3
"""
Build the askamerica-mcp standalone binary using PyInstaller.

Usage:
    pip install pyinstaller jdk4py jpype1 mcp
    python build_mcp_binary.py

Output: dist/askamerica-mcp  (or dist/askamerica-mcp.exe on Windows)
"""
import os
import platform
import subprocess
import sys
from pathlib import Path


def main():
    here = Path(__file__).parent
    system = platform.system()
    sep = ";" if system == "Windows" else ":"

    # Locate jdk4py's bundled JDK — must be installed at build time
    try:
        from jdk4py import JAVA_HOME
    except ImportError:
        sys.exit("jdk4py not installed. Run: pip install jdk4py")

    # Locate jpype's native extension directory
    try:
        import jpype
        jpype_dir = Path(jpype.__file__).parent
    except ImportError:
        sys.exit("jpype1 not installed. Run: pip install jpype1")

    entry = here / "askamerica" / "mcp_server.py"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "askamerica-mcp",
        # Bundle the entire jdk4py JDK so _get_jvm_path() finds it in _MEIPASS
        "--add-data", f"{JAVA_HOME}{sep}jdk4py/java-runtime",
        # JPype native libs
        "--add-data", f"{jpype_dir}{sep}jpype",
        "--hidden-import", "askamerica.engine",
        "--hidden-import", "askamerica.config",
        "--hidden-import", "askamerica.exceptions",
        "--hidden-import", "jpype",
        "--hidden-import", "jpype._jpype",
        "--hidden-import", "mcp",
        "--hidden-import", "mcp.server.fastmcp",
        "--hidden-import", "anyio",
        "--hidden-import", "starlette",
        "--collect-all", "mcp",
        "--collect-all", "anyio",
        str(entry),
    ]

    print(f"Building askamerica-mcp binary for {system}...")
    subprocess.run(cmd, check=True, cwd=here)
    print(f"\nBinary: {here / 'dist' / ('askamerica-mcp.exe' if system == 'Windows' else 'askamerica-mcp')}")
    print("\nClaude Desktop config:")
    binary = ("askamerica-mcp.exe" if system == "Windows" else "askamerica-mcp")
    print(f"""
  "askamerica": {{
    "command": "/path/to/{binary}",
    "env": {{
      "ASKAMERICA_API_KEY": "aa_free_..."
    }}
  }}
""")


if __name__ == "__main__":
    main()
