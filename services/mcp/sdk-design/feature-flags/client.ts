import type { RequestOptions } from '../client'
import type { FeatureFlagsArchiveInput, FeatureFlagsArchiveOutput } from './archive'
import type { FeatureFlagsListInput, FeatureFlagsListOutput } from './list'

export interface FeatureFlagsClient {
    /**
     * Get feature flags in the current project. Supports list filters including search by feature flag key or name
     * (case-insensitive), then use the returned ID for get/update/delete tools. Pass `active: "STALE"` to list
     * only stale flags. PostHog calls a flag stale when it is enabled and was last called over 30 days ago, or was
     * never called, is over 30 days old and is rolled out to everyone. The filter does not return a never-called
     * flag with an empty `groups` list in `filters`, even when `feature-flags-status-retrieve` calls it stale.
     * Stale flags are cleanup candidates, not proof that a flag is unused. Disabled flags are not checked for
     * staleness, so `status: ACTIVE` on a disabled flag is expected. Each row carries `status`, `last_called_at`,
     * `active` and `created_at`. For the reason behind one flag's status, and its rollout summary, use
     * `feature-flags-status-retrieve`.
     *
     * @remarks Returns one page. Related MCP tool names are resolved through the package catalog, including tools without an SDK method.
     * @mcpTool feature-flag-get-all
     * @requiredScopes feature_flag:read
     * @see products/feature_flags/mcp/tools.yaml#/tools/feature-flag-get-all/description
     */
    list(input: FeatureFlagsListInput, options?: RequestOptions): Promise<FeatureFlagsListOutput>

    /**
     * Archive a feature flag, hiding it from the default flag list. Requires the flag's numeric ID; use
     * `feature-flag-get-definition-by-key` to get it from a key, or `feature-flag-get-all` to search by key or
     * name.
     *
     * Sets `archived` to true. An archived flag must be disabled, so an enabled flag is turned off in the same
     * call. Nothing else changes: this tool never accepts or replaces the `filters` object, and linked experiment
     * and survey history is preserved. There is no request body.
     *
     * When the flag is enabled, archiving stops it evaluating everywhere. Tell the user what else this affects:
     * linked experiments, surveys, early access features and session replay settings all appear in the flag's full
     * definition.
     *
     * Returns 400 when the flag is enabled and other active flags depend on it. Returns 409 when an approval
     * policy gates disabling. Archiving an already-archived flag succeeds and changes nothing, so retrying is
     * safe.
     *
     * `feature-flag-get-definition-by-key` also finds archived flags, so a flag that is already archived is
     * returned with `archived: true` rather than looking missing on a retry. `feature-flag-get-all` hides archived
     * flags unless you pass `{"archived":"true"}`.
     *
     * Use `feature-flag-unarchive` to put the flag back in the list, or `delete-feature-flag` when the user wants
     * it gone rather than tidied away.
     *
     * @remarks Related MCP tool names are resolved through the package catalog, including tools without an SDK method.
     * @mcpTool feature-flag-archive
     * @requiredScopes feature_flag:write
     * @see products/feature_flags/mcp/tools.yaml#/tools/feature-flag-archive/description
     */
    archive(input: FeatureFlagsArchiveInput, options?: RequestOptions): Promise<FeatureFlagsArchiveOutput>
}
