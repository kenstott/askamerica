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
    from .engine import download_jar
    try:
        download_jar(version=getattr(args, "version", None))
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


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
