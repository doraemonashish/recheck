"""Fetch real release histories from PyPI: the change trace behind experiment E11.

"What is the latest version of package X?" is a fact every coding agent remembers and every
coding agent gets wrong once it goes stale. PyPI's JSON API gives each release's upload time, so
the true answer is known at every moment. For each package this keeps the stable releases (no
pre-releases, no yanked files) with the time of their first upload; the latest version at time t
is the highest version uploaded by t, which is what `pip install X` resolves to.

    python scripts/fetch_pypi_traces.py            # writes data/pypi_releases.json.gz

The output is committed, so experiments never need the network.
"""
from __future__ import annotations

import gzip
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from packaging.version import InvalidVersion, Version

PACKAGES = """
numpy pandas scipy matplotlib scikit-learn requests urllib3 certifi idna charset-normalizer
setuptools pip wheel packaging six python-dateutil pytz tzdata pyyaml attrs typing-extensions
click jinja2 markupsafe werkzeug flask django fastapi starlette uvicorn gunicorn pydantic
pydantic-core sqlalchemy alembic psycopg2-binary pymysql redis celery kombu boto3 botocore
s3transfer awscli google-cloud-storage google-api-core protobuf grpcio cryptography pyopenssl
cffi pycparser rsa pyasn1 oauthlib requests-oauthlib aiohttp yarl multidict frozenlist
aiosignal async-timeout httpx httpcore anyio sniffio h11 websockets tornado pytest pluggy
iniconfig coverage pytest-cov tox virtualenv filelock platformdirs black isort flake8
pycodestyle pyflakes mypy ruff pylint astroid tqdm rich pygments colorama tabulate pillow
opencv-python imageio scikit-image torch torchvision transformers tokenizers huggingface-hub
safetensors datasets accelerate sentencepiece tensorflow keras jax jaxlib xgboost lightgbm
catboost statsmodels seaborn plotly bokeh networkx sympy numba llvmlite pyarrow polars
duckdb openpyxl xlrd lxml beautifulsoup4 soupsieve html5lib docutils sphinx markdown
mkdocs nltk spacy gensim openai langchain tiktoken regex jsonschema
referencing rpds-py fsspec s3fs cloudpickle dill joblib psutil wrapt decorator
cachetools tenacity more-itertools zipp importlib-metadata toml tomli tomlkit
paramiko pynacl bcrypt docker kubernetes ansible-core jmespath python-dotenv
""".split()


def _fetch(name: str) -> tuple[str, list[tuple[str, str]] | None]:
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        print(f"skip {name}: {e}", file=sys.stderr)
        return name, None
    out = []
    for ver, files in data.get("releases", {}).items():
        try:
            v = Version(ver)
        except InvalidVersion:
            continue
        if v.is_prerelease or v.is_devrelease:
            continue
        files = [f for f in files if not f.get("yanked")]
        if not files:
            continue
        first = min(f["upload_time_iso_8601"] for f in files)
        out.append((first, ver))
    out.sort()
    return name, out


def latest_trace(releases: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(time, latest version) at each moment the highest uploaded version changes."""
    trace, best = [], None
    for t, ver in releases:
        v = Version(ver)
        if best is None or v > best:
            best = v
            trace.append((t, ver))
    return trace


def main() -> None:
    with ThreadPoolExecutor(16) as ex:
        res = dict(ex.map(_fetch, PACKAGES))
    traces = {n: latest_trace(r) for n, r in res.items() if r}
    out = Path(__file__).resolve().parents[1] / "data" / "pypi_releases.json.gz"
    out.parent.mkdir(exist_ok=True)
    payload = {"fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "packages": PACKAGES,
               "latest": traces}
    with gzip.open(out, "wt") as f:
        json.dump(payload, f)
    n = sum(len(v) for v in traces.values())
    print(f"{len(traces)} packages, {n} changes of the latest version -> {out}")


if __name__ == "__main__":
    main()
