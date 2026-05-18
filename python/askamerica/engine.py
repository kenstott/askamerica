"""
JVM lifecycle and JDBC connection management for the askamerica-engine JAR.
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .config import API_BASE_URL, load_config, save_config
from .exceptions import AuthError, EngineNotInstalledError

DEFAULT_JAR_PATH = Path.home() / ".askamerica" / "engine" / "askamerica-engine.jar"

# Schemas loaded by default — publicly accessible without per-schema API keys.
DEFAULT_SCHEMAS = (
    "sec,geo,econ,census,crime,weather,ref,fec,"
    "fedregister,cyber_vuln,cyber_threat,energy,health,edu,econ_reference"
)

_jvm_started = False
_conn = None


def get_engine_jar() -> str:
    jar = os.environ.get("ASKAMERICA_ENGINE_JAR")
    if jar and Path(jar).exists():
        return jar
    if DEFAULT_JAR_PATH.exists():
        return str(DEFAULT_JAR_PATH)
    raise EngineNotInstalledError(
        "askamerica-engine JAR not found.\n"
        "Run: askamerica install-engine\n"
        "Or set: export ASKAMERICA_ENGINE_JAR=/path/to/askamerica-engine.jar"
    )


def get_r2_credentials(api_key: str) -> dict:
    config = load_config()
    cached = config.get("r2_credentials")
    if cached:
        return cached

    resp = requests.get(
        f"{API_BASE_URL}/v1/catalog/credentials",
        headers={"X-API-Key": api_key},
        timeout=10,
    )
    if resp.status_code == 401:
        raise AuthError("Invalid or expired API key. Run: askamerica login")
    resp.raise_for_status()
    creds = resp.json()

    config["r2_credentials"] = creds
    save_config(config)
    return creds


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

    # Inject R2 credentials as env vars before JVM starts (govdata reads these).
    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        creds = get_r2_credentials(api_key)
        os.environ["AWS_ACCESS_KEY_ID"] = creds["access_key_id"]
        os.environ["AWS_SECRET_ACCESS_KEY"] = creds["secret_access_key"]
        os.environ.setdefault("AWS_REGION", creds.get("region", "auto"))
        endpoint = creds.get("endpoint", "")
        if endpoint:
            os.environ.setdefault("AWS_ENDPOINT_URL_S3", endpoint)

    jpype.startJVM(classpath=[jar_path], convertStrings=False)
    _jvm_started = True


def get_connection(api_key: str):
    global _conn
    start_jvm(api_key)

    if _conn is None:
        import jpype
        schemas = os.environ.get("ASKAMERICA_SCHEMAS", DEFAULT_SCHEMAS)
        GovDataDriver = jpype.JClass(
            "org.apache.calcite.adapter.govdata.GovDataDriver"
        )
        driver = GovDataDriver()
        props = jpype.JClass("java.util.Properties")()
        url = f"jdbc:govdata:source={schemas}"
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
