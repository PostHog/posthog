# Today

## Highlight sources ("For you today")

Today ranks facts that other products find and shows the best few.
The product that owns the data owns its source: the query, the thresholds, and the copy.
Today owns the contract, the ranking, and the shared helpers.
Today also owns the pulse: the routine and key-metric tiles, pinned numbers, and the home dashboard source.
These live in `backend/logic/today_highlights/` and Today declares them in `backend/facade/today_highlights.py`.

**A source that another team owns lives in that team's product, never in `products/today/`.**
The how-to for a product team is the `adding-today-highlights` skill (`.agents/skills/adding-today-highlights/SKILL.md`), because a producer works in its own product and never loads this file.

Today finds every declaration through `posthog.products.load_product_modules`, so a new source changes no backend file in Today.
The registry raises on a missing declaration, an unusable entry, or a source name that another product already uses.
It also records the product that declares each source, and the row icon comes from that product (`PRODUCT_ICONS` in `frontend/src/scenes/project-homepage/today/todayRowIcons.tsx`).

The facade (`contracts.py`, `enums.py`, `highlight_helpers.py`, `testing.py`) is a contract with every producing product.
Change it only in a backward-compatible way: an added field gets a default, because Today validates stored results against these types.

**Status:** every other team's source lives in its own product.
`backend/logic/highlight_sources/` and its `SOURCE` lookup are gone, so a file there no longer loads.
