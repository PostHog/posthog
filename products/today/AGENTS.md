# Today

## Highlight sources ("For you today")

Today ranks facts that other products find and shows the best few.
The product that owns the data owns its source: the query, the thresholds, and the copy.
Today owns the contract, the ranking, and the shared helpers.

**A new source lives in its own product, never in `products/today/`.**

1. Put the rule in the product's internals, for example `products/<x>/backend/today_highlights.py`.
   It takes a `HighlightContext` and returns `HighlightFindings`.
2. Declare it in `products/<x>/backend/facade/today_highlights.py`:

   ```python
   from products.today.backend.facade.contracts import HighlightSource

   from ..today_highlights import find_stale_things

   HIGHLIGHT_SOURCES = (HighlightSource(name="stale_things", find=find_stale_things, scopes=("thing:read",)),)
   ```

3. Add `"products.today"` to the product's `depends_on` in `tach.toml`. Today gets no new dependency.
4. Test the rule in the product, with `products.today.backend.facade.testing.highlight_context`.

Today finds the declaration through `posthog.products.load_product_modules`, so a new source changes no file in Today.
The registry raises on a missing declaration, an unusable entry, or a source name that another product already uses.

Import only from Today's facade:

- `facade/contracts.py`: `HighlightCandidate`, `HighlightFindings`, `HighlightContext`, `HighlightSource`, `HighlightMetric`, `DailyValueNotReady`
- `facade/enums.py`: `HighlightLabel`, `HighlightUnit`, `HighlightInterval`
- `facade/highlight_helpers.py`: number and text formatting, `uses_product`, and trend detection

`HighlightContext.daily()` caches one value per team, property restrictions and day, so every viewer with the same restrictions shares it.
Never compute a per-viewer value there without the user id in its name.

**Status:** `backend/logic/highlight_sources/` is deprecated.
The sources in it still load, through legacy aliases in `logic/highlight_types.py`, until each one moves into its product.
Do not add a file there and do not copy those files as an example.
