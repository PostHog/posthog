# Error tracking MCP definitions

`error_tracking_alerts.yaml` is a subset file (not synced by `scaffold-yaml --sync-all` beyond validation) that wraps the generic `hog_functions_*` operations as error-tracking alert tools.

Maintainer notes:

- Tool descriptions and the `authoring-error-tracking-alerts` skill ship to external MCP clients — never reference repo paths or internal code in them.
- The block payloads embedded in the create-tool description and in `products/error_tracking/skills/authoring-error-tracking-alerts/references/block-templates.md` mirror `HOG_FUNCTION_SUB_TEMPLATES` (error-tracking entries) in `frontend/src/scenes/hog-functions/sub-templates/sub-templates.ts` — keep them in sync when the sub-templates change.
- Comments in `error_tracking_alerts.yaml` do not survive `scaffold-yaml --sync-all` (the file is re-emitted with a fixed header), which is why these notes live here.
