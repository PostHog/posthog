/**
 * Collects the operationIds and per-operation exclude_params of one MCP YAML definition's enabled tools.
 *
 * exclude_params are removed from the operation's schema before Orval runs, and every tool on that operation
 * shares the schema. So every enabled tool on one operation must declare the same list, an empty one included:
 * otherwise whichever tool is read last would decide the schema for all of them. Tools with their own
 * input_schema don't use the operation's schema, so their lists aren't compared.
 *
 * @param {Record<string, any> | undefined} tools the definition's `tools` map
 * @param {string} source where the definition came from, for the error message
 * @returns {{ operationIds: Set<string>, schemaExclusions: Map<string, string[]> }}
 */
export function collectToolExclusions(tools, source) {
    const operationIds = new Set()
    /** @type {Map<string, string[]>} */
    const schemaExclusions = new Map()
    /** @type {Map<string, { owner: string, key: string }>} */
    const seen = new Map()

    for (const [name, tool] of Object.entries(tools ?? {})) {
        if (!tool?.enabled || !tool?.operation) {
            continue
        }
        operationIds.add(tool.operation)
        if (tool.input_schema) {
            continue
        }
        const excludeParams = tool.exclude_params ?? []
        const key = [...excludeParams].sort().join(',')
        const previous = seen.get(tool.operation)
        if (previous && previous.key !== key) {
            throw new Error(
                `${source}: ${previous.owner} and ${name} both use ${tool.operation} with different exclude_params. ` +
                    'The operation has one schema, so the lists must match.'
            )
        }
        seen.set(tool.operation, { owner: name, key })
        if (excludeParams.length > 0) {
            schemaExclusions.set(tool.operation, excludeParams)
        }
    }
    return { operationIds, schemaExclusions }
}
