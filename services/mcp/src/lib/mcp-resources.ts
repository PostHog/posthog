export const MCP_RESOURCE_CATEGORIES = ['skills', 'docs', 'apps'] as const

export type McpResourceCategory = (typeof MCP_RESOURCE_CATEGORIES)[number]

/** Parsed `?resources=` / `x-posthog-mcp-resources` selection for a connection. */
export type McpResourcesSelection =
    | { policy: 'all' }
    | { policy: 'none' }
    | { policy: 'include'; categories: readonly McpResourceCategory[] }

export const MCP_RESOURCES_ALL: McpResourcesSelection = { policy: 'all' }

// Context-mill manifest URIs use `posthog://skills/…` and `posthog://docs/…` (see latest
// skills-mcp-resources.zip). UI apps use `ui://posthog/…`.
const CATEGORY_BY_PREFIX: ReadonlyArray<{ prefix: string; category: McpResourceCategory }> = [
    { prefix: 'posthog://skills/', category: 'skills' },
    { prefix: 'posthog://docs/', category: 'docs' },
    { prefix: 'ui://posthog/', category: 'apps' },
]

const VALID_CATEGORY = new Set<string>(MCP_RESOURCE_CATEGORIES)

/**
 * Caller-supplied resource surface, parallel to `parseMcpMode`.
 * Absent or all-unknown values → full catalog (`policy: 'all'`).
 */
export function parseMcpResources(raw: string | null | undefined): McpResourcesSelection {
    if (raw == null) {
        return { policy: 'all' }
    }
    const trimmed = raw.trim()
    if (!trimmed) {
        return { policy: 'all' }
    }
    const value = trimmed.toLowerCase()
    if (value === 'none') {
        return { policy: 'none' }
    }
    const categories: McpResourceCategory[] = []
    const seen = new Set<McpResourceCategory>()
    for (const part of value.split(',')) {
        const token = part.trim()
        if (!token) {
            continue
        }
        if (token === 'none') {
            return { policy: 'none' }
        }
        if (!VALID_CATEGORY.has(token)) {
            continue
        }
        const category = token as McpResourceCategory
        if (!seen.has(category)) {
            seen.add(category)
            categories.push(category)
        }
    }
    if (categories.length === 0) {
        return { policy: 'all' }
    }
    return { policy: 'include', categories }
}

/** Header wins over query, matching `parseMcpMode` / `parseRequestProperties` wiring. */
export function parseMcpResourcesFromConnection(
    headerValue: string | null | undefined,
    queryValue: string | null | undefined
): McpResourcesSelection {
    return parseMcpResources(headerValue || queryValue)
}

/** Partial test fixtures may omit `mcpResources`; production paths always parse one. */
export function mcpResourcesFor(selection: McpResourcesSelection | undefined): McpResourcesSelection {
    return selection ?? MCP_RESOURCES_ALL
}

export function resourceCategoryForUri(uri: string): McpResourceCategory | undefined {
    for (const { prefix, category } of CATEGORY_BY_PREFIX) {
        if (uri.startsWith(prefix)) {
            return category
        }
    }
    return undefined
}

export function isResourceUriIncluded(uri: string, selection: McpResourcesSelection): boolean {
    if (selection.policy === 'all') {
        return true
    }
    if (selection.policy === 'none') {
        return false
    }
    const category = resourceCategoryForUri(uri)
    if (!category) {
        return false
    }
    return selection.categories.includes(category)
}

export function filterResourcesBySelection<T extends { uri: string }>(
    resources: readonly T[],
    selection: McpResourcesSelection
): T[] {
    if (selection.policy === 'all') {
        return resources as T[]
    }
    return resources.filter((r) => isResourceUriIncluded(r.uri, selection))
}
