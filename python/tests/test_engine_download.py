"""Unit tests for engine.py's jar download path (mocked network)."""
from unittest.mock import patch

from askamerica import engine


def test_download_jar_is_atomic(tmp_path):
    """A download must never leave a partially-written file at the live jar path."""
    dest = tmp_path / "askamerica-engine.jar"
    release = {
        "tag_name": "engine-v1.0.0",
        "assets": [{"name": "askamerica-engine.jar", "size": 1024,
                    "browser_download_url": "https://example.invalid/jar"}],
    }

    def fake_urlretrieve(url, filename, reporthook=None):
        with open(filename, "wb") as f:
            f.write(b"jar-bytes")

    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("urllib.request.urlretrieve", side_effect=fake_urlretrieve):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = \
            __import__("json").dumps(release).encode()
        result = engine.download_jar(dest=dest)

    assert result == dest
    assert dest.read_bytes() == b"jar-bytes"
    assert list(tmp_path.glob("*.tmp-*")) == []


def test_download_jar_failure_leaves_no_partial_file(tmp_path):
    """If the download itself fails, the live jar path must be untouched."""
    dest = tmp_path / "askamerica-engine.jar"
    dest.write_bytes(b"previous-good-jar")
    release = {
        "tag_name": "engine-v1.0.0",
        "assets": [{"name": "askamerica-engine.jar", "size": 1024,
                    "browser_download_url": "https://example.invalid/jar"}],
    }

    def fake_urlretrieve(url, filename, reporthook=None):
        with open(filename, "wb") as f:
            f.write(b"partial")
        raise IOError("connection reset")

    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("urllib.request.urlretrieve", side_effect=fake_urlretrieve):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = \
            __import__("json").dumps(release).encode()
        try:
            engine.download_jar(dest=dest)
            assert False, "expected the simulated download failure to propagate"
        except IOError:
            pass

    assert dest.read_bytes() == b"previous-good-jar"
    assert list(tmp_path.glob("*.tmp-*")) == []
