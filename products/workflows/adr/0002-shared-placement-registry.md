# One placement registry in `products/workflows/mcp/`, shared by the web slot and the MCP

Every messaging call-to-action spot is one entry in `products/workflows/mcp/messagingPlacements.ts`, with its area flag, variant, calls to action, audience kind and default copy.
The web slot and the MCP guidance rule both decide whether a spot shows by calling the same pure `placementState(key, flags)`.
We put it in `mcp/`, not `frontend/`, because `services/mcp` imports from `products/*/mcp/` already and the frontend does too, so one file serves both without a new package.
We considered a copy of the placement keys and flag logic on each side, but they would drift, and the experiment needs the holdout and the variant read the same way on both surfaces.

## Consequences

The registry must stay free of browser and Node-only imports, since both builds compile it.
A placement key is frozen once it ships, because events and flag variants carry it.
See `docs/architecture/messaging-cta-slot.md`.
