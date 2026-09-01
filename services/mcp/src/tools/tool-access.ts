/**
 * Access class of a tool: what a call to it can do to the caller's data.
 *
 * Derived from the MCP annotations every tool already carries, so `exec tools`
 * and `exec search` can answer "is this safe to call?" in the discovery payload.
 * Without it an agent must run `exec info` once per tool to read the same hints.
 */
export type ToolAccess = 'read' | 'write' | 'destructive'

/** The subset of a tool needed to classify it, kept structural so a scope-gated
 *  entry or a third-party tool works without a full `Tool`. */
export type AccessAnnotatedTool = {
    name: string
    annotations: {
        readOnlyHint: boolean
        destructiveHint: boolean
    }
}

export function classifyToolAccess(tool: AccessAnnotatedTool): ToolAccess {
    if (tool.annotations.readOnlyHint) {
        return 'read'
    }
    return tool.annotations.destructiveHint ? 'destructive' : 'write'
}

/**
 * Splits tool names into the three access classes, keeping the input order
 * inside each class. Every name lands in exactly one list, so the partition
 * costs no more names than a flat listing does.
 */
export function partitionToolsByAccess(tools: readonly AccessAnnotatedTool[]): Record<ToolAccess, string[]> {
    const partitioned: Record<ToolAccess, string[]> = { read: [], write: [], destructive: [] }
    for (const tool of tools) {
        partitioned[classifyToolAccess(tool)].push(tool.name)
    }
    return partitioned
}

/**
 * Names the tools in `names` that are not read-only, for a payload that already
 * lists every match in relevance order. Only the exceptions are repeated, so
 * anything absent from both lists is read-only.
 */
export function listWriteAndDestructive(
    names: readonly string[],
    tools: readonly AccessAnnotatedTool[]
): { write?: string[]; destructive?: string[] } {
    const byName = new Map(tools.map((tool) => [tool.name, tool]))
    const matched = names.map((name) => byName.get(name)).filter((tool) => tool !== undefined)
    const { write, destructive } = partitionToolsByAccess(matched)
    return {
        ...(write.length > 0 ? { write } : {}),
        ...(destructive.length > 0 ? { destructive } : {}),
    }
}
