# Signals frontend

The web inbox (reports, scouts, sources and settings) lives here.
Follow [frontend/src/AGENTS.md](../../../frontend/src/AGENTS.md) for all other frontend rules.

## The inbox supports phone widths

This file overrides the "Do not build for mobile" bullet of Rule 6 in `frontend/src/AGENTS.md` for this directory.
People open inbox reports on their phones, for example from a notification or a link in Slack, so the inbox is a mobile-supported surface.
The rest of Rule 6 still applies.

- **A phone is the narrowest container, not a separate layout.** Keep breaking on container queries. A layout that holds at a ~520px scene must keep going down to a ~360px viewport: rows wrap or stack, long strings truncate, nothing scrolls sideways except a tab bar or a chip row built to scroll.
- **Every action has a tap path.** An action that appears only on hover, such as a row action or a tooltip that holds the only explanation, also needs a path without hover.
- **Render at phone width before calling the work done.** Check ~390px as well as the narrow-scene width, and pin a narrow width in a story when a layout depends on it.
