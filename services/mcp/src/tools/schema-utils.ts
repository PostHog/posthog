/** Token-aware schema summarization and drill-down utilities for the exec tool. */

// 12k tokens × 4 chars/token
export const TOKEN_CHAR_LIMIT = 4 * 12_000

type JSONSchema = Record<string, unknown>

interface SummarizedProperty {
    type?: string
    description?: string
    enum?: unknown[]
    default?: unknown
    const?: unknown
    required?: boolean
    fields?: string[]
    items?: string
    hint?: string
}

/**
 * A summarized schema node. `properties` is always present (empty for non-object
 * nodes) so callers can read it unconditionally; `items` (arrays) and `variants`
 * (unions) carry the recursive shape that the old object-only summarizer dropped.
 */
interface NodeSummary {
    type: string
    title?: string
    required?: string[]
    properties: Record<string, SummarizedProperty>
    items?: NodeSummary
    variants?: NodeSummary[]
    description?: string
    enum?: unknown[]
    const?: unknown
    default?: unknown
}

/**
 * Properties that conventionally discriminate a union variant. Zod discriminated
 * unions (e.g. the trends `series` EventsNode/ActionsNode/GroupNode split) carry the
 * variant identity in one of these as a `const`/single-value `enum`, not in `title`.
 */
const DISCRIMINATOR_KEYS = ['kind', 'type', 'nodeKind'] as const

/** Best-effort human label for a union variant: `title`, a root `const`, or a discriminator property's `const`/single-value `enum`. */
function variantName(variant: JSONSchema): string | undefined {
    if (typeof variant.title === 'string') {
        return variant.title
    }
    if (typeof variant.const === 'string') {
        return variant.const
    }
    const props = variant.properties as Record<string, JSONSchema> | undefined
    if (!props) {
        return undefined
    }
    for (const key of DISCRIMINATOR_KEYS) {
        const disc = props[key]
        if (!disc) {
            continue
        }
        if (typeof disc.const === 'string') {
            return disc.const
        }
        if (Array.isArray(disc.enum) && disc.enum.length === 1 && typeof disc.enum[0] === 'string') {
            return disc.enum[0]
        }
    }
    return undefined
}

/**
 * Describe the type of a union (anyOf/oneOf) concisely.
 * Names variants via `variantName` (title, root const, or discriminator const).
 */
function describeUnion(variants: JSONSchema[]): string {
    const names = variants.map(variantName).filter((n): n is string => typeof n === 'string')
    if (names.length > 0 && names.length <= 6) {
        return `union of ${variants.length} types (${names.join(', ')})`
    }
    return `union of ${variants.length} types`
}

/** Get the effective type string for a schema node. */
function getTypeString(schema: JSONSchema): string {
    if (typeof schema.type === 'string') {
        return schema.type
    }
    if (Array.isArray(schema.type)) {
        return (schema.type as string[]).filter((t) => t !== 'null').join(' | ')
    }
    if (schema.anyOf || schema.oneOf) {
        const variants = (schema.anyOf || schema.oneOf) as JSONSchema[]
        // Filter out null types for optional unions
        const nonNull = variants.filter((v) => v.type !== 'null')
        if (nonNull.length === 0) {
            return 'null'
        }
        return describeUnion(nonNull)
    }
    if (schema.const !== undefined) {
        return 'const'
    }
    return 'unknown'
}

/** Check if a property has complex nested structure that needs drill-down. */
function isComplex(schema: JSONSchema): boolean {
    if (schema.type === 'object' && schema.properties) {
        return true
    }
    if (schema.type === 'array' && schema.items) {
        const items = schema.items as JSONSchema
        if (items.type === 'object' && items.properties) {
            return true
        }
        if (items.anyOf || items.oneOf) {
            return true
        }
    }
    if (schema.anyOf || schema.oneOf) {
        const variants = (schema.anyOf || schema.oneOf) as JSONSchema[]
        const nonNull = variants.filter((v) => v.type !== 'null')
        // Simple nullable scalar is not complex
        if (nonNull.length <= 1 && nonNull.every((v) => typeof v.type === 'string' && v.type !== 'object')) {
            return false
        }
        return nonNull.length > 1 || nonNull.some((v) => v.type === 'object' || v.type === 'array')
    }
    return false
}

/** Describe array items concisely. */
function describeItems(items: JSONSchema): string {
    if (items.anyOf || items.oneOf) {
        const variants = (items.anyOf || items.oneOf) as JSONSchema[]
        return describeUnion(variants.filter((v) => v.type !== 'null'))
    }
    if (items.type === 'object') {
        const propNames = items.properties ? Object.keys(items.properties as Record<string, unknown>) : []
        if (propNames.length > 0) {
            return `object with ${propNames.length} fields`
        }
        return 'object'
    }
    return getTypeString(items)
}

// Defensive recursion bound for `summarizeNode`. Zod's `toJSONSchema` inlines, so
// schemas are finite trees, but array/union unwrapping recurses — cap it anyway.
const MAX_SUMMARY_DEPTH = 6

/**
 * Summarize an object's top-level properties: field names, types, descriptions,
 * and drill-down hints for complex fields. Intentionally does NOT recurse into a
 * nested object/array/union field — each complex field instead carries a `hint`
 * pointing at the next `schema <tool> <path>` call.
 */
function summarizeObject(schema: JSONSchema, toolName: string, fieldPath?: string): NodeSummary {
    const properties = (schema.properties || {}) as Record<string, JSONSchema>
    const requiredFields = (schema.required || []) as string[]
    const result: Record<string, SummarizedProperty> = {}
    const pathPrefix = fieldPath ? `${fieldPath}.` : ''

    for (const [name, prop] of Object.entries(properties)) {
        const entry: SummarizedProperty = {}
        entry.type = getTypeString(prop)

        if (typeof prop.description === 'string') {
            entry.description = prop.description
        }
        if (prop.enum) {
            entry.enum = prop.enum as unknown[]
        }
        if (prop.default !== undefined) {
            entry.default = prop.default
        }
        if (prop.const !== undefined) {
            entry.const = prop.const
        }
        if (requiredFields.includes(name)) {
            entry.required = true
        }

        // For objects, list subfield names
        if (prop.type === 'object' && prop.properties) {
            entry.fields = Object.keys(prop.properties as Record<string, unknown>)
        }

        // For arrays, describe items
        if (prop.type === 'array' && prop.items) {
            entry.items = describeItems(prop.items as JSONSchema)
        }

        // Add drill-down hint for complex fields. Phrased as an imperative, not a
        // description — models observably treat declarative notes as advisory, so
        // the directive lives on the field the model is about to populate.
        if (isComplex(prop)) {
            entry.hint = `DO NOT GUESS — you MUST run \`schema ${toolName} ${pathPrefix}${name}\` before populating this field`
        }

        result[name] = entry
    }

    const summary: NodeSummary = {
        type: (schema.type as string) || 'object',
        ...(requiredFields.length > 0 ? { required: requiredFields } : {}),
        properties: result,
    }
    if (typeof schema.title === 'string') {
        summary.title = schema.title
    }
    return summary
}

/** Summarize a scalar/leaf node — its descriptive metadata only, no children. */
function summarizeLeaf(schema: JSONSchema): NodeSummary {
    const summary: NodeSummary = { type: getTypeString(schema), properties: {} }
    if (typeof schema.title === 'string') {
        summary.title = schema.title
    }
    if (typeof schema.description === 'string') {
        summary.description = schema.description
    }
    if (schema.enum) {
        summary.enum = schema.enum as unknown[]
    }
    if (schema.const !== undefined) {
        summary.const = schema.const
    }
    if (schema.default !== undefined) {
        summary.default = schema.default
    }
    return summary
}

/**
 * Summarize any schema node, dispatching on its kind.
 *
 * Array and union WRAPPERS recurse, unlike the per-field summary inside an object
 * (which stops at one level and emits a `hint`). The reason: `items` and union
 * variants don't consume a path segment — `resolveSchemaPath` walks through them
 * transparently (`series.event` reaches into `series`'s array-of-union items) — so
 * a faithful summary has to unwrap them until it reaches the object/scalar beneath.
 * Without this, summarizing an array- or union-typed field that overflows the inline
 * budget (e.g. `query-trends series`) collapsed to an empty `{ type, properties: {} }`
 * and the variant shapes were invisible.
 */
function summarizeNode(
    schema: JSONSchema,
    toolName: string,
    fieldPath: string | undefined,
    depth: number
): NodeSummary {
    // Union: summarize each non-null variant. A lone non-null variant (a nullable
    // wrapper) collapses to that variant so we don't emit a pointless 1-way union.
    const unionVariants = (schema.anyOf || schema.oneOf) as JSONSchema[] | undefined
    if (unionVariants) {
        const nonNull = unionVariants.filter((v) => v.type !== 'null')
        if (nonNull.length === 0) {
            return { type: 'null', properties: {} }
        }
        if (depth >= MAX_SUMMARY_DEPTH) {
            return { type: getTypeString(schema), properties: {} }
        }
        if (nonNull.length === 1) {
            // Unwrap a nullable wrapper. Count it against `depth` so a pathological
            // chain of nested nullable unions still terminates at MAX_SUMMARY_DEPTH.
            return summarizeNode(nonNull[0]!, toolName, fieldPath, depth + 1)
        }
        return {
            type: getTypeString(schema),
            properties: {},
            variants: nonNull.map((v) => summarizeNode(v, toolName, fieldPath, depth + 1)),
        }
    }

    // Array: summarize the item schema (which itself may be an object or a union).
    if (schema.type === 'array' && schema.items && !Array.isArray(schema.items)) {
        const items = schema.items as JSONSchema
        if (depth >= MAX_SUMMARY_DEPTH) {
            return { type: 'array', properties: {}, items: { type: describeItems(items), properties: {} } }
        }
        return { type: 'array', properties: {}, items: summarizeNode(items, toolName, fieldPath, depth + 1) }
    }

    // Object with properties: list field names + drill-down hints (one level deep).
    if (schema.properties) {
        return summarizeObject(schema, toolName, fieldPath)
    }

    // A property-less object keeps the historical empty shape; anything else is a leaf.
    if (schema.type === 'object') {
        return { type: 'object', properties: {} }
    }
    return summarizeLeaf(schema)
}

/**
 * Summarize a JSON Schema for the `info` / `schema` exec commands.
 *
 * Objects list their top-level properties with drill-down hints; arrays and unions
 * recurse through the wrapper into the underlying item/variant shapes, so the result
 * is never an empty `{ type, properties: {} }`.
 */
export function summarizeSchema(schema: JSONSchema, toolName: string, fieldPath?: string): NodeSummary {
    return summarizeNode(schema, toolName, fieldPath, 0)
}

/**
 * JSON Schema composition keywords that fan out into more sub-schemas.
 * A named child may live under any of these; resolution walks them transparently.
 */
const COMPOSITION_KEYS = ['allOf', 'anyOf', 'oneOf'] as const

function getVariants(node: JSONSchema, key: (typeof COMPOSITION_KEYS)[number]): JSONSchema[] | undefined {
    const value = node[key]
    return Array.isArray(value) ? (value as JSONSchema[]) : undefined
}

/**
 * Find a named child of a schema node, regardless of how the schema composes it.
 *
 * Walks `properties`, every composition keyword (`allOf`/`anyOf`/`oneOf`), and `items`
 * recursively — so `series.event` works whether `event` lives on `items.properties`,
 * `items.anyOf[i].properties`, `items.allOf[i].properties`, or any nested combination.
 *
 * First match wins. `seen` blocks pathological cycles if schemas ever carry self-refs
 * (Zod's `toJSONSchema` inlines, so this is defensive).
 */
function findNamedChild(node: JSONSchema, name: string, seen: WeakSet<JSONSchema> = new WeakSet()): JSONSchema | null {
    if (seen.has(node)) {
        return null
    }
    seen.add(node)

    if (node.properties) {
        const direct = (node.properties as Record<string, JSONSchema>)[name]
        if (direct) {
            return direct
        }
    }

    for (const key of COMPOSITION_KEYS) {
        const variants = getVariants(node, key)
        if (!variants) {
            continue
        }
        for (const variant of variants) {
            const hit = findNamedChild(variant, name, seen)
            if (hit) {
                return hit
            }
        }
    }

    // Array children are whatever `items` exposes — recurse transparently.
    // Tuple form (`items: [...]`) is ignored; Zod doesn't produce it and it would need
    // index-specific handling anyway.
    if (node.items && !Array.isArray(node.items)) {
        const hit = findNamedChild(node.items as JSONSchema, name, seen)
        if (hit) {
            return hit
        }
    }

    return null
}

/**
 * Resolve a numeric index: descend into array items or pick a union variant by position.
 * Arrays take precedence (all items share the same schema, so index 0/N returns the
 * same items wrapper); for unions, `0` picks the first variant, `1` the second, etc.
 */
function findIndexedChild(node: JSONSchema, idx: number): JSONSchema | null {
    if (node.items && !Array.isArray(node.items)) {
        return node.items as JSONSchema
    }
    for (const key of COMPOSITION_KEYS) {
        const variants = getVariants(node, key)
        if (variants && variants[idx]) {
            return variants[idx] as JSONSchema
        }
    }
    return null
}

/**
 * Collect every named child reachable from a node by walking composition keywords.
 * Dedupes across variants.
 *
 * `descendItems` controls whether the walk crosses the array boundary. It must stay
 * off for `listAvailablePaths`, which labels item children separately as
 * `[items].<name>`; glob expansion turns it on to reach every name a literal segment
 * could resolve (see `collectResolvableChildNames`).
 */
function collectNamedChildren(
    node: JSONSchema,
    into: Set<string> = new Set(),
    seen: WeakSet<JSONSchema> = new WeakSet(),
    descendItems = false
): Set<string> {
    if (seen.has(node)) {
        return into
    }
    seen.add(node)

    if (node.properties) {
        for (const k of Object.keys(node.properties as Record<string, unknown>)) {
            into.add(k)
        }
    }
    for (const key of COMPOSITION_KEYS) {
        const variants = getVariants(node, key)
        if (!variants) {
            continue
        }
        for (const variant of variants) {
            collectNamedChildren(variant, into, seen, descendItems)
        }
    }
    if (descendItems && node.items && !Array.isArray(node.items)) {
        collectNamedChildren(node.items as JSONSchema, into, seen, descendItems)
    }
    return into
}

/** Resolve one literal path segment: numeric segments try the index first, then the name. */
function resolveLiteralSegment(node: JSONSchema, segment: string): JSONSchema | null {
    if (/^\d+$/.test(segment)) {
        return findIndexedChild(node, parseInt(segment, 10)) ?? findNamedChild(node, segment)
    }
    return findNamedChild(node, segment)
}

/**
 * Resolve a dot-separated path within a JSON Schema.
 * Returns the sub-schema at that path, or null if invalid.
 */
export function resolveSchemaPath(schema: JSONSchema, dotPath: string): JSONSchema | null {
    let current: JSONSchema = schema
    for (const segment of dotPath.split('.')) {
        const next = resolveLiteralSegment(current, segment)
        if (!next) {
            return null
        }
        current = next
    }
    return current
}

/**
 * List available child paths from a schema node.
 * Emits:
 *   - every named child reachable through any composition keyword (direct or nested)
 *   - `[items].<name>` for array-of-object/array-of-union items (via composition walk)
 *   - numeric variant labels when the node itself is a union
 */
export function listAvailablePaths(schema: JSONSchema): string[] {
    const paths: string[] = []

    // Named children at this level (covers properties + allOf/anyOf/oneOf at any nesting).
    for (const k of collectNamedChildren(schema)) {
        paths.push(k)
    }

    // Array item children, surfaced under `[items].<name>` so callers know they're
    // indexing through an array.
    if (schema.type === 'array' && schema.items && !Array.isArray(schema.items)) {
        const itemChildren = collectNamedChildren(schema.items as JSONSchema)
        for (const k of itemChildren) {
            paths.push(`[items].${k}`)
        }
    }

    // If the node is itself a union, expose variant indices so callers can pick by position.
    for (const key of COMPOSITION_KEYS) {
        const variants = getVariants(schema, key)
        if (!variants || key === 'allOf') {
            continue
        }
        for (let i = 0; i < variants.length; i++) {
            const v = variants[i]!
            const label = typeof v.title === 'string' ? `${i} (${v.title})` : `${i}`
            paths.push(label)
        }
    }

    return paths
}

/**
 * The named children `findNamedChild` can resolve on a node: `collectNamedChildren`'s
 * walk with `descendItems` on, since a literal segment reaches through `items` too.
 */
function collectResolvableChildNames(node: JSONSchema, into: Set<string> = new Set()): Set<string> {
    return collectNamedChildren(node, into, new WeakSet(), true)
}

/** Escape a string for literal use inside a `RegExp`. */
function escapeRegex(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** The concrete paths a single `schema` pattern expands to, plus the schema at each. */
export interface SchemaPathExpansion {
    matches: Array<{ path: string; schema: JSONSchema }>
    truncated: boolean
    /** Populated only when nothing matched — the resolvable names at the failing depth. */
    available?: string[]
}

/**
 * Backstop against a combinatorial mid-pattern blow-up (`*.*.*` across wide unions).
 * Deliberately far above any caller's `limit`: intermediate frontiers must survive
 * uncut so later segments can still filter them; only the FINAL matches are capped
 * at `limit`. Cutting mid-walk both hides reachable paths and flags `truncated` on
 * results that end up complete.
 */
const MAX_FRONTIER_NODES = 512

/** Cap on the `available` names reported when a pattern matches nothing; keeps error
 *  entries small enough that a failing batch can't blow the response budget. */
const MAX_AVAILABLE_NAMES = 50

/**
 * Expand one dot-path pattern into concrete `(path, schema)` pairs.
 *
 * A segment containing `*` is a glob matched against the resolvable child names of
 * each frontier node; every segment (glob-matched names included) binds through
 * `resolveLiteralSegment`, so an emitted path always re-resolves to the same node in
 * a later single-path `resolveSchemaPath` call, even for all-digit property names
 * where the index-first rule would otherwise win.
 *
 * When the frontier collapses to nothing, `available` lists the names reachable at
 * the depth that failed (not the root), so the caller's error points at the
 * offending segment.
 */
export function expandSchemaPathPattern(schema: JSONSchema, pattern: string, limit: number): SchemaPathExpansion {
    let frontier: Array<{ path: string; node: JSONSchema }> = [{ path: '', node: schema }]
    let truncated = false

    for (const segment of pattern.split('.')) {
        const matcher = segment.includes('*') ? new RegExp(`^${escapeRegex(segment).replaceAll('\\*', '.*')}$`) : null
        const next: Array<{ path: string; node: JSONSchema }> = []

        for (const entry of frontier) {
            if (matcher) {
                for (const name of collectResolvableChildNames(entry.node)) {
                    if (!matcher.test(name)) {
                        continue
                    }
                    const child = resolveLiteralSegment(entry.node, name)
                    if (child) {
                        next.push({ path: entry.path ? `${entry.path}.${name}` : name, node: child })
                    }
                }
            } else {
                const child = resolveLiteralSegment(entry.node, segment)
                if (child) {
                    next.push({ path: entry.path ? `${entry.path}.${segment}` : segment, node: child })
                }
            }
        }

        if (next.length === 0) {
            // Frontier collapsed here: report the names that WERE reachable on the
            // nodes we tried to descend from, so the error names the failing depth.
            const available = new Set<string>()
            for (const entry of frontier) {
                collectResolvableChildNames(entry.node, available)
            }
            return { matches: [], truncated, available: [...available].slice(0, MAX_AVAILABLE_NAMES) }
        }
        if (next.length > MAX_FRONTIER_NODES) {
            next.length = MAX_FRONTIER_NODES
            truncated = true
        }
        frontier = next
    }

    if (frontier.length > limit) {
        frontier.length = limit
        truncated = true
    }
    return { matches: frontier.map((e) => ({ path: e.path, schema: e.node })), truncated }
}

/**
 * One entry in a batched `schema` response: a resolved sub-schema, a per-path error,
 * or a stub pointing at a solo `schema` call when the sub-schema can't fit inline
 * alongside its siblings.
 */
export type SchemaFieldEntry =
    | { field: string; schema: unknown }
    | { field: string; error: string; available?: string[] }
    | { field: string; hint: string }

/** Stub text for a field dropped from a combined response to stay within budget. */
function schemaStubHint(toolName: string, field: string): string {
    return `Too large for a combined response; run \`schema ${toolName} ${field}\` alone.`
}

interface BudgetedEntry {
    field: string
    /** The full resolved schema; present only for degradable (schema) entries. */
    schema?: JSONSchema
    /** 'error' entries can shed their `available` list; 'fixed' entries cannot shrink. */
    state: 'full' | 'summary' | 'stub' | 'error' | 'fixed'
    current: SchemaFieldEntry
    len: number
}

/** The largest entry in a given state; ties keep the earliest request index. */
function largestInState(entries: BudgetedEntry[], state: BudgetedEntry['state']): BudgetedEntry | undefined {
    let best: BudgetedEntry | undefined
    for (const entry of entries) {
        if (entry.state === state && (!best || entry.len > best.len)) {
            best = entry
        }
    }
    return best
}

/**
 * Fit a batch of resolved schema entries within `charBudget` (the combined `fields`
 * array minus the response envelope). Accounts for each serialized entry plus the
 * commas that join them. Degrades greedily, largest-first, cheapest information
 * loss first: a full schema becomes a `summarizeSchema` summary, then error entries
 * shed their `available` sibling lists (guidance, not content), and only then does
 * a summary collapse to a one-line stub. One huge field can't force its siblings to
 * collapse. Preserves request order.
 */
export function budgetSchemaFields(
    entries: SchemaFieldEntry[],
    toolName: string,
    charBudget: number
): SchemaFieldEntry[] {
    const tracked: BudgetedEntry[] = entries.map((entry) => {
        const len = JSON.stringify(entry).length
        if ('schema' in entry) {
            return { field: entry.field, schema: entry.schema as JSONSchema, state: 'full', current: entry, len }
        }
        if ('error' in entry && entry.available?.length) {
            return { field: entry.field, state: 'error', current: entry, len }
        }
        return { field: entry.field, state: 'fixed', current: entry, len }
    })

    // Total = serialized entries + the commas joining them (the enclosing `fields`
    // array and envelope keys are already subtracted from `charBudget` by the caller).
    const total = (): number => tracked.reduce((sum, e) => sum + e.len, 0) + Math.max(0, tracked.length - 1)

    // Summarize the largest still-full schema until it fits or none remain.
    while (total() > charBudget) {
        const target = largestInState(tracked, 'full')
        if (!target) {
            break
        }
        const summarized: SchemaFieldEntry = {
            field: target.field,
            schema: summarizeSchema(target.schema!, toolName, target.field),
        }
        target.current = summarized
        target.len = JSON.stringify(summarized).length
        target.state = 'summary'
    }

    // Still over: drop `available` from the largest error entries before touching
    // any summary, so schema content survives the longest.
    while (total() > charBudget) {
        const target = largestInState(tracked, 'error')
        if (!target) {
            break
        }
        const bare: SchemaFieldEntry = { field: target.field, error: (target.current as { error: string }).error }
        target.current = bare
        target.len = JSON.stringify(bare).length
        target.state = 'fixed'
    }

    // Still over: stub the largest summary until it fits or none remain.
    while (total() > charBudget) {
        const target = largestInState(tracked, 'summary')
        if (!target) {
            break
        }
        const stub: SchemaFieldEntry = { field: target.field, hint: schemaStubHint(toolName, target.field) }
        target.current = stub
        target.len = JSON.stringify(stub).length
        target.state = 'stub'
    }

    return tracked.map((e) => e.current)
}
