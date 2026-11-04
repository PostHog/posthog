import type { ScoutToolCatalogueApi, ScoutToolCatalogueEntryApi } from 'products/signals/frontend/generated/api.schemas'

export interface ScoutToolGroup {
    category: string
    tools: ScoutToolCatalogueEntryApi[]
}

/** Why a tool cannot go on a list, or undefined when it can. */
export function scoutToolUnavailableReason(tool: ScoutToolCatalogueEntryApi): string | undefined {
    return tool.holdable ? undefined : 'No scout can hold the access this tool needs'
}

/** The catalogue tools a list can name: everything except the run context tools. */
export function selectableScoutTools(catalogue: ScoutToolCatalogueApi): ScoutToolCatalogueEntryApi[] {
    return catalogue.tools.filter((tool) => !catalogue.run_context_tools.includes(tool.name))
}

/** Labels for the run context tools, for the always-held group. A tool the catalogue lacks shows its name. */
export function runContextScoutToolLabels(catalogue: ScoutToolCatalogueApi): string[] {
    return catalogue.run_context_tools.map((name) => catalogue.tools.find((tool) => tool.name === name)?.title || name)
}

/**
 * Selectable tools grouped by category, narrowed to the ones whose name, title, summary, or category
 * contains the search text. Groups and tools are in alphabetical order.
 */
export function groupScoutTools(catalogue: ScoutToolCatalogueApi, search: string): ScoutToolGroup[] {
    const needle = search.trim().toLowerCase()
    const matches = selectableScoutTools(catalogue).filter(
        (tool) =>
            !needle ||
            [tool.name, tool.title, tool.summary, tool.category].some((text) => text.toLowerCase().includes(needle))
    )
    const byCategory = new Map<string, ScoutToolCatalogueEntryApi[]>()
    for (const tool of matches) {
        byCategory.set(tool.category, [...(byCategory.get(tool.category) ?? []), tool])
    }
    return [...byCategory.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([category, tools]) => ({
            category,
            tools: [...tools].sort((a, b) => a.title.localeCompare(b.title)),
        }))
}

/**
 * The write scopes a saved list gives the scout. Mirrors the derivation in
 * `_resolve_scout_config_grants` in `products/signals/backend/scout_harness/views.py`: the required
 * scopes of each chosen write tool, limited to the scopes a person can grant.
 */
export function deriveScoutToolWriteScopes(catalogue: ScoutToolCatalogueApi, selected: readonly string[]): string[] {
    const derived = new Set<string>()
    for (const tool of catalogue.tools) {
        if (tool.is_read_only || !selected.includes(tool.name)) {
            continue
        }
        for (const scope of tool.required_scopes) {
            if (catalogue.grantable_write_scopes.includes(scope)) {
                derived.add(scope)
            }
        }
    }
    return [...derived].sort()
}
