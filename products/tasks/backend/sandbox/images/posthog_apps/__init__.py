import pandas as _pd
import requests as _requests

_BRIDGE_URL = "http://127.0.0.1:8181/_bridge/query"


def query(hogql: str) -> _pd.DataFrame:
    """Run a HogQL query against PostHog from inside a Streamlit sandbox."""
    resp = _requests.post(_BRIDGE_URL, json={"query": hogql}, timeout=60)
    if resp.status_code != 200:
        try:
            err = resp.json().get("error", resp.text)
        except Exception:
            err = resp.text
        raise RuntimeError("HogQL query failed: " + str(err))
    data = resp.json()
    columns = data.get("columns", [])
    results = data.get("results", [])
    return _pd.DataFrame(results, columns=columns)
