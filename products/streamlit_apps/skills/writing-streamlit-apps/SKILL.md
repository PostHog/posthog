---
name: writing-streamlit-apps
description: Write Streamlit app source code that runs well in a PostHog sandbox — the posthog_apps.query() bridge for reading PostHog data, the packages baked into the sandbox image, caching and session state across Streamlit reruns, layout and chart patterns, and single-file app.py structure. Use when authoring or debugging the Python source of a PostHog Streamlit app, when a query inside an app fails, or when asked to "write a streamlit app that shows PostHog data".
---

# Writing Streamlit apps for the PostHog sandbox

The source you write becomes `app.py` at the root of a sandboxed Streamlit 1.31 runtime.
Deployment mechanics (create/start/share) are the `managing-streamlit-apps` skill; this one is about the code.

## Reading PostHog data: `posthog_apps.query()`

The one and only data door is the in-sandbox bridge:

```python
import posthog_apps

df = posthog_apps.query("SELECT event, count() FROM events GROUP BY event LIMIT 10")
```

- Takes a HogQL string, returns a **pandas DataFrame**.
- Raises `RuntimeError` on failure. The message is deliberately generic ("Query execution failed") — the bridge does not return query internals to the sandbox, so you cannot diagnose a bad query from inside the app. Catch it and render with `st.error(str(e))` so viewers get a message instead of a stack trace, and test queries in the SQL editor where real errors are visible.
- `import posthog` does NOT exist in the sandbox — the module is `posthog_apps`, deliberately distinct from the posthog-python SDK's name.
- The bridge is pre-authenticated to the app's project; user code never sees a token, and there is nothing to configure.
- Queries run with server-side caps (30 s execution, 256 MB memory) that don't scale with sandbox sizing — so bound time ranges, `LIMIT` results, and aggregate in HogQL rather than pulling raw events into pandas.

## Design for Streamlit's rerun model

Streamlit reruns the whole script top to bottom on every widget interaction.
Two consequences:

1. **Cache every bridge call** — uncached, one slider drag re-fires every query:

   ```python
   @st.cache_data(ttl=300, show_spinner="Running query...")
   def run_query(hogql: str) -> pd.DataFrame:
       return posthog_apps.query(hogql)
   ```

2. **Use `st.session_state` for anything that must survive reruns** — accumulated selections, pagination cursors, "last refreshed" stamps. Module-level variables reset on every interaction.

Widgets drive parameters naturally, but **never interpolate a free-text widget value into HogQL**.
The bridge runs your query with the version author's data access, and anyone who can view the app drives those widgets — a raw `st.text_input` spliced into a query hands viewers the author's access to write their own.
Constrain the input instead: pick from a fixed list you control (`st.selectbox` over known values), or coerce to a type that can't carry SQL (`int(days)`, a `date` from `st.date_input`), and validate before it reaches the query.

## Layout and charts

- `st.set_page_config(page_title=..., layout="wide")` first — the default narrow layout wastes most of the screen for data apps.
- Structure with `st.columns` for side-by-side metrics, `st.tabs` for alternate views, `st.expander` for detail sections; `st.metric` for headline numbers.
- Charts: `st.plotly_chart(fig, use_container_width=True)` with plotly express is the reliable default; `st.dataframe(df, use_container_width=True)` for tables. matplotlib/seaborn also work via `st.pyplot`.

## What's installed

The image ships Python 3.11 with: `streamlit` 1.31, `pandas`, `numpy`, `polars`, `plotly`, `matplotlib`, `seaborn`, `scipy`, `scikit-learn`, `pyarrow`, `duckdb`, `requests`, `beautifulsoup4`, `lxml`, `sqlalchemy`, `aiohttp`.
There is no way to add dependencies: the sandbox never runs pip (a deliberate security posture — no arbitrary package code at boot), and a `requirements.txt` in an uploaded zip is tolerated but dropped. Only import what's listed above.

## Structure and runtime constraints

- **One file.** Via the MCP set-source flow your source IS `app.py`; there are no other modules, so keep everything in it.
- The sandbox is ephemeral: anything written to disk disappears on stop/restart. Don't build state on files; recompute from queries (with caching) or hold it in `st.session_state`.
- Your code runs as an unprivileged user; there's no posthog SDK, no way to pass your own environment variables or secrets to the app, and no expectation of general network egress. Don't read from `os.environ` — anything there belongs to the sandbox runtime, not your app. Design around `posthog_apps.query()` as the data source.

## A minimal well-shaped app

```python
import pandas as pd
import plotly.express as px
import posthog_apps
import streamlit as st

st.set_page_config(page_title="Events overview", layout="wide")
st.title("Events overview")


@st.cache_data(ttl=300, show_spinner="Running query...")
def run_query(hogql: str) -> pd.DataFrame:
    return posthog_apps.query(hogql)


# A slider is bounded and coerced to int, so it is safe to interpolate.
days = int(st.slider("Days to show", 1, 30, 7))
try:
    daily = run_query(
        f"""
        SELECT toDate(timestamp) AS day, count() AS events
        FROM events
        WHERE timestamp >= now() - INTERVAL {days} DAY
        GROUP BY day ORDER BY day
        """
    )
    st.plotly_chart(px.bar(daily, x="day", y="events"), use_container_width=True)
except RuntimeError as e:
    st.error(str(e))
```
