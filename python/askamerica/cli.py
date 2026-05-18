import sys
import argparse
from .auth import login
from .quota import get_quota
from .config import get_api_key
from .exceptions import AuthError


def cmd_login(args: argparse.Namespace) -> None:
    login(email=getattr(args, "email", None))


def cmd_quota(args: argparse.Namespace) -> None:
    key = get_api_key()
    if not key:
        print("Not logged in. Run: askamerica login")
        sys.exit(1)
    try:
        quota = get_quota(key)
        used_gb = quota["used_bytes"] / (1024 ** 3)
        limit_gb = quota["limit_bytes"] / (1024 ** 3)
        remaining_gb = quota["remaining_bytes"] / (1024 ** 3)
        pct = (quota["used_bytes"] / quota["limit_bytes"]) * 100
        print(f"Period:    {quota['period']}")
        print(f"Used:      {used_gb:.3f} GB of {limit_gb:.0f} GB ({pct:.1f}%)")
        print(f"Remaining: {remaining_gb:.3f} GB")
        if quota["remaining_bytes"] < quota["limit_bytes"] * 0.2:
            print(f"Upgrade:   {quota['upgrade_url']}")
    except AuthError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_whoami(args: argparse.Namespace) -> None:
    from .config import load_config
    config = load_config()
    if not config:
        print("Not logged in. Run: askamerica login")
        sys.exit(1)
    print(f"Email: {config.get('email', 'unknown')}")
    print(f"Tier:  {config.get('tier', 'free')}")
    key = config.get("api_key", "")
    print(f"Key:   {key[:12]}...{key[-4:] if len(key) > 16 else ''}")


def cmd_install_engine(args: argparse.Namespace) -> None:
    import os
    import platform
    import urllib.request
    from pathlib import Path

    install_dir = Path.home() / ".askamerica" / "engine"
    install_dir.mkdir(parents=True, exist_ok=True)
    jar_path = install_dir / "askamerica-engine.jar"

    # Resolve version: explicit arg, or latest from GitHub
    version = getattr(args, "version", None)
    if not version:
        import json
        api_url = "https://api.github.com/repos/kenstott/calcite/releases"
        with urllib.request.urlopen(api_url, timeout=15) as r:
            releases = json.loads(r.read())
        engine_releases = [
            rel for rel in releases
            if rel.get("tag_name", "").startswith("engine-v")
            and not rel.get("prerelease")
        ]
        if not engine_releases:
            print("No engine releases found on GitHub. Build manually:")
            print("  ./gradlew :askamerica-engine:shadowJar")
            sys.exit(1)
        version = engine_releases[0]["tag_name"].lstrip("engine-v")
        tag = engine_releases[0]["tag_name"]
        assets = engine_releases[0].get("assets", [])
    else:
        tag = f"engine-v{version}"
        import json
        api_url = f"https://api.github.com/repos/kenstott/calcite/releases/tags/{tag}"
        with urllib.request.urlopen(api_url, timeout=15) as r:
            release = json.loads(r.read())
        assets = release.get("assets", [])

    # Find the JAR asset (not an installer)
    jar_asset = next(
        (a for a in assets if a["name"] == "askamerica-engine.jar"), None
    )
    if not jar_asset:
        print(f"No askamerica-engine.jar asset found in release {tag}.")
        print("Available assets:")
        for a in assets:
            print(f"  {a['name']}")
        sys.exit(1)

    url = jar_asset["browser_download_url"]
    size_mb = jar_asset["size"] / (1024 * 1024)
    print(f"Downloading askamerica-engine.jar ({size_mb:.0f} MB) ...")
    print(f"  from: {url}")
    print(f"  to:   {jar_path}")

    def progress(block_num, block_size, total_size):
        if total_size > 0:
            pct = min(100, block_num * block_size * 100 // total_size)
            print(f"\r  {pct}%", end="", flush=True)

    urllib.request.urlretrieve(url, jar_path, reporthook=progress)
    print(f"\nInstalled: {jar_path}")
    print("Test with: python -c \"import askamerica as aa; print(aa.query.__doc__)\"")


def cmd_mcp_config(args: argparse.Namespace) -> None:
    import json
    import platform
    from pathlib import Path

    key = get_api_key()
    if not key:
        print("Not logged in. Run: askamerica login")
        sys.exit(1)

    config = {
        "mcpServers": {
            "askamerica": {
                "command": sys.executable,
                "args": ["-m", "askamerica.mcp_server"],
                "env": {
                    "ASKAMERICA_API_KEY": key,
                },
            }
        }
    }

    if platform.system() == "Darwin":
        config_path = (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    elif platform.system() == "Windows":
        config_path = (
            Path(os.environ.get("APPDATA", Path.home()))
            / "Claude"
            / "claude_desktop_config.json"
        )
    else:
        config_path = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"

    print("Add this block to your Claude Desktop config:")
    print(f"  {config_path}\n")
    print(json.dumps(config, indent=2))
    print()

    if config_path.exists():
        print("Your current config already exists — merge the mcpServers block manually.")
    else:
        choice = input("Write this config now? [y/N] ").strip().lower()
        if choice == "y":
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            print(f"Written to {config_path}")
            print("Restart Claude Desktop to activate.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="askamerica",
        description="AskAmerica — query US government data",
    )
    sub = parser.add_subparsers(dest="command")

    p_login = sub.add_parser("login", help="Authenticate and get an API key")
    p_login.add_argument("--email", help="Email address (optional, prompted if omitted)")

    sub.add_parser("quota", help="Show current quota usage")
    sub.add_parser("whoami", help="Show current login info")

    p_engine = sub.add_parser("install-engine", help="Download the query engine JAR")
    p_engine.add_argument(
        "--version", help="Engine version to install (default: latest)"
    )

    sub.add_parser(
        "mcp-config",
        help="Print Claude Desktop MCP configuration snippet",
    )

    args = parser.parse_args()

    if args.command == "login":
        cmd_login(args)
    elif args.command == "quota":
        cmd_quota(args)
    elif args.command == "whoami":
        cmd_whoami(args)
    elif args.command == "install-engine":
        cmd_install_engine(args)
    elif args.command == "mcp-config":
        cmd_mcp_config(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
