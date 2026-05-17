import hashlib
import json
from pathlib import Path
import pandas as pd

CACHE_DIR = Path("cache")
GEOMETRIES_FILE = CACHE_DIR / "geometries.parquet"
RESULTS_FILE = CACHE_DIR / "results.parquet"


def geometry_hash(params: dict) -> str:
    """Canonical hash of geometry parameters."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def register_geometry(params: dict) -> str:
    """Add geometry to cache if new. Returns its hash either way."""
    h = geometry_hash(params)
    CACHE_DIR.mkdir(exist_ok=True)

    if GEOMETRIES_FILE.exists():
        df = pd.read_parquet(GEOMETRIES_FILE)
        if h in df["geometry_hash"].values:
            return h
    else:
        df = pd.DataFrame(columns=["geometry_hash", "parameters_json", "created_at"])

    new_row = pd.DataFrame([{
        "geometry_hash": h,
        "parameters_json": json.dumps(params, sort_keys=True, separators=(",", ":")),
        "created_at": pd.Timestamp.now(tz="UTC"),
    }])
    pd.concat([df, new_row], ignore_index=True).to_parquet(GEOMETRIES_FILE, index=False)
    return h


def append_results(rows: list[dict]) -> None:
    """Append result rows. Each row matches the results schema."""
    new_df = pd.DataFrame(rows)
    if RESULTS_FILE.exists():
        existing = pd.read_parquet(RESULTS_FILE)
        new_df = pd.concat([existing, new_df], ignore_index=True)
    new_df.to_parquet(RESULTS_FILE, index=False)


def query_results(geometry_hash: str, **filters) -> pd.DataFrame:
    """Return cached rows matching geometry_hash and any column filters."""
    if not RESULTS_FILE.exists():
        return pd.DataFrame()
    df = pd.read_parquet(RESULTS_FILE)
    df = df[df["geometry_hash"] == geometry_hash]
    for col, val in filters.items():
        df = df[df[col] == val]
    return df
