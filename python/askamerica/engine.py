"""
JVM lifecycle and JDBC connection management for the askamerica-engine JAR.
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import load_config, save_config
from .exceptions import AuthError, EngineNotInstalledError

DEFAULT_JAR_PATH = Path.home() / ".askamerica" / "engine" / "askamerica-engine.jar"

# Pinned at publish time by the engine release workflow — matches engine-v<version> tag.
BUNDLED_ENGINE_VERSION = "0.18.2"

# Schemas loaded by default — publicly accessible without per-schema API keys.
DEFAULT_SCHEMAS = (
    "sec,geo,econ,census,crime,weather,ref,fec,"
    "fedregister,cyber_vuln,cyber_threat,energy,health,edu,econ_reference"
)

_jvm_started = False
_conn = None


def download_jar(version: str = None, dest: Path = DEFAULT_JAR_PATH) -> Path:
    import json
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)

    # Default to the version bundled at package-publish time so pip install
    # askamerica==X.Y.Z always fetches the matching engine JAR.
    effective_version = version or BUNDLED_ENGINE_VERSION

    tag = f"engine-v{effective_version}"
    url = f"https://api.github.com/repos/kenstott/calcite/releases/tags/{tag}"
    with urllib.request.urlopen(url, timeout=15) as r:
        release = json.loads(r.read())

    assets = release.get("assets", [])
    jar_asset = next((a for a in assets if a["name"] == "askamerica-engine.jar"), None)
    if not jar_asset:
        raise EngineNotInstalledError(
            f"No askamerica-engine.jar asset in release {release['tag_name']}."
        )

    download_url = jar_asset["browser_download_url"]
    size_mb = jar_asset["size"] / (1024 * 1024)
    print(f"Downloading askamerica-engine.jar ({size_mb:.0f} MB)...")

    def _progress(block_num, block_size, total_size):
        if total_size > 0:
            pct = min(100, block_num * block_size * 100 // total_size)
            print(f"\r  {pct}%", end="", flush=True)

    urllib.request.urlretrieve(download_url, dest, reporthook=_progress)
    print(f"\nEngine ready: {dest}")
    return dest


def get_engine_jar() -> str:
    jar = os.environ.get("ASKAMERICA_ENGINE_JAR")
    if jar and Path(jar).exists():
        return jar
    if DEFAULT_JAR_PATH.exists():
        return str(DEFAULT_JAR_PATH)
    # Auto-download on first use
    return str(download_jar())


def _get_jvm_path() -> Optional[str]:
    """Return libjvm path — prefers jdk4py bundle, falls back to system JVM."""
    import platform
    import sys
    system = platform.system()

    def _lib_for(base: Path) -> Path:
        if system == "Darwin":
            return base / "lib" / "server" / "libjvm.dylib"
        if system == "Windows":
            return base / "bin" / "server" / "jvm.dll"
        return base / "lib" / "server" / "libjvm.so"

    # PyInstaller one-file bundle: jdk4py data files are extracted to _MEIPASS
    if getattr(sys, "frozen", False):
        lib = _lib_for(Path(sys._MEIPASS) / "jdk4py" / "java-runtime")
        if lib.exists():
            return str(lib)

    # Normal Python env with jdk4py installed
    try:
        from jdk4py import JAVA_HOME
        lib = _lib_for(JAVA_HOME)
        if lib.exists():
            return str(lib)
    except ImportError:
        pass

    return None


def start_jvm(api_key: str) -> None:
    global _jvm_started

    try:
        import jpype
    except ImportError:
        raise ImportError(
            "jpype1 is not installed.\n"
            "Run: pip install 'askamerica[engine]'  or  pip install jpype1"
        )

    if jpype.isJVMStarted():
        _jvm_started = True
        return

    if _jvm_started:
        return

    jar_path = get_engine_jar()

    # Ensure ASKAMERICA_API_KEY is visible to the JVM for credential refresh if needed.
    if api_key and not os.environ.get("ASKAMERICA_API_KEY"):
        os.environ["ASKAMERICA_API_KEY"] = api_key

    jvm_path = _get_jvm_path()
    if jvm_path:
        jpype.startJVM(jvm_path, classpath=[jar_path], convertStrings=False)
    else:
        jpype.startJVM(classpath=[jar_path], convertStrings=False)
    _jvm_started = True


def get_connection(api_key: str):
    global _conn
    start_jvm(api_key)

    if _conn is None:
        import jpype
        schemas = os.environ.get("ASKAMERICA_SCHEMAS", DEFAULT_SCHEMAS)
        AskAmericaDriver = jpype.JClass(
            "org.apache.calcite.adapter.askamerica.AskAmericaDriver"
        )
        driver = AskAmericaDriver()
        props = jpype.JClass("java.util.Properties")()
        url = f"jdbc:askamerica:source={schemas}"
        _conn = driver.connect(url, props)

    return _conn


def execute_query(conn, sql: str) -> List[Dict[str, Any]]:
    stmt = conn.createStatement()
    try:
        rs = stmt.executeQuery(sql)
        meta = rs.getMetaData()
        col_count = meta.getColumnCount()
        columns = [str(meta.getColumnName(i + 1)) for i in range(col_count)]
        rows = []
        while rs.next():
            row: Dict[str, Any] = {}
            for i, col in enumerate(columns):
                val = rs.getObject(i + 1)
                row[col] = None if rs.wasNull() else _to_python(val)
            rows.append(row)
        rs.close()
        return rows
    finally:
        stmt.close()


def _to_python(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (bool, int, float, str)):
        return val
    # JPype proxy — convert to string for anything else (dates, BigDecimal, etc.)
    return str(val)


def get_metadata(conn):
    return conn.getMetaData()
