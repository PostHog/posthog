/**
 * JSON Schema → TypeScript interface emitter for the SDK prototype.
 *
 * Emits flat, grep-friendly declarations: every object with properties becomes a named
 * `export interface`, every `$ref` to an OpenAPI component or a schema.json definition is
 * a one-hop reference to a shared named interface, and nothing is expressed through
 * mapped/conditional types that only a type checker can resolve.
 */

export type JsonSchema = Record<string, any>

export interface EmitContext {
    /** OpenAPI `components.schemas` (for `#/components/schemas/X`). */
    components: Record<string, JsonSchema>
    /** schema.json `definitions` (for `#/definitions/X`). */
    defs: Record<string, JsonSchema>
    /** Declarations hoisted into the file being generated, keyed by name, in emission order. */
    localDecls: Map<string, string>
    /** Structural hash → hoisted name, so an inlined schema reused inside one file is declared once. */
    structural: Map<string, string>
    /** Shared OpenAPI components referenced from this file. */
    sharedUsed: Set<string>
    /** Shared schema.json definitions referenced from this file. */
    queryDefsUsed: Set<string>
    /** Root schema, for `#/$defs/...` refs zod emits for recursive schemas. */
    root?: JsonSchema
    /** Name of the Input/Output interface being declared; prefixes hoisted copies of shared entities. */
    currentRoot?: string
}

const COMPONENT_PREFIX = '#/components/schemas/'
const DEF_PREFIX = '#/definitions/'
const ZOD_DEFS_PREFIX = '#/$defs/'

const JSDOC_TAGS = [
    'default',
    'minimum',
    'maximum',
    'exclusiveMinimum',
    'exclusiveMaximum',
    'minLength',
    'maxLength',
    'minItems',
    'maxItems',
    'pattern',
    'format',
] as const

export function pascal(input: string): string {
    return input
        .replace(/[^A-Za-z0-9]+/g, ' ')
        .trim()
        .split(' ')
        .map((s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : ''))
        .join('')
}

export function isIdentifier(name: string): boolean {
    return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name)
}

function propertyKey(name: string): string {
    return isIdentifier(name) ? name : JSON.stringify(name)
}

function escapeDoc(text: string): string {
    return text.replace(/\*\//g, '*\\/')
}

export function renderJsDoc(lines: string[], indent = ''): string {
    const flat = lines.flatMap((line) => escapeDoc(line).split('\n'))
    if (flat.length === 0) {
        return ''
    }
    if (flat.length === 1 && flat[0]!.length < 100) {
        return `${indent}/** ${flat[0]} */\n`
    }
    return `${indent}/**\n${flat.map((line) => `${indent} * ${line}`.replace(/\s+$/, '')).join('\n')}\n${indent} */\n`
}

function docLinesFor(schema: JsonSchema, extra: string[] = []): string[] {
    const lines: string[] = []
    if (typeof schema.description === 'string' && schema.description.trim()) {
        lines.push(schema.description.trim())
    }
    lines.push(...extra)
    for (const tag of JSDOC_TAGS) {
        if (schema[tag] !== undefined) {
            lines.push(`@${tag} ${typeof schema[tag] === 'string' ? schema[tag] : JSON.stringify(schema[tag])}`)
        }
    }
    if (schema.readOnly) {
        lines.push('@readonly')
    }
    if (schema['x-required-when-set']) {
        lines.push(`@requiredWhenSet ${JSON.stringify(schema['x-required-when-set'])}`)
    }
    if (schema.discriminator?.propertyName) {
        lines.push(`@discriminator ${schema.discriminator.propertyName}`)
    }
    return lines
}

function hashOf(value: unknown): string {
    return JSON.stringify(value)
}

export function resolveRef(
    ref: string,
    ctx: EmitContext
): { name: string; schema: JsonSchema | undefined; kind: 'component' | 'def' | 'local' } {
    if (ref.startsWith(COMPONENT_PREFIX)) {
        const name = ref.slice(COMPONENT_PREFIX.length)
        return { name, schema: ctx.components[name], kind: 'component' }
    }
    if (ref.startsWith(DEF_PREFIX)) {
        const name = ref.slice(DEF_PREFIX.length)
        return { name, schema: ctx.defs[name], kind: 'def' }
    }
    if (ref.startsWith(ZOD_DEFS_PREFIX)) {
        const name = ref.slice(ZOD_DEFS_PREFIX.length)
        return { name, schema: ctx.root?.$defs?.[name], kind: 'local' }
    }
    throw new Error(`Unsupported $ref: ${ref}`)
}

function isNullSchema(schema: JsonSchema): boolean {
    return schema.type === 'null' || (schema.const === null && Object.keys(schema).length === 1)
}

function parenthesize(expr: string): string {
    return /[|&]/.test(expr) && !expr.startsWith('(') ? `(${expr})` : expr
}

/**
 * Render the TypeScript type expression for a schema. Objects with properties are hoisted into
 * a named interface (returned by name); everything else is returned inline.
 */
export function typeExpr(schema: JsonSchema, ctx: EmitContext, hint: string): string {
    if (!schema || typeof schema !== 'object') {
        return 'unknown'
    }
    if (typeof schema.$ref === 'string') {
        const { name, kind, schema: target } = resolveRef(schema.$ref, ctx)
        if (kind === 'component') {
            ctx.sharedUsed.add(name)
            return name
        }
        if (kind === 'def') {
            ctx.queryDefsUsed.add(name)
            return name
        }
        // zod recursive schema: hoist under a local name once.
        const localName = `${hint}${pascal(name)}`
        if (!ctx.localDecls.has(localName) && target) {
            ctx.localDecls.set(localName, '') // reserve to break recursion
            const decl = declareNamed(localName, target, ctx, [])
            ctx.localDecls.set(localName, decl)
        }
        return localName
    }

    const nullable = schema.nullable === true
    const withNull = (expr: string): string => (nullable ? `${expr} | null` : expr)

    if (schema.const !== undefined) {
        return withNull(JSON.stringify(schema.const))
    }
    if (Array.isArray(schema.enum)) {
        const values = schema.enum.map((v: unknown) => JSON.stringify(v))
        return withNull(values.length ? values.join(' | ') : 'never')
    }

    const variants: JsonSchema[] | undefined = schema.anyOf ?? schema.oneOf
    if (Array.isArray(variants)) {
        const parts: string[] = []
        let sawNull = false
        variants.forEach((variant, index) => {
            if (isNullSchema(variant)) {
                sawNull = true
                return
            }
            const variantHint = variantName(variant, hint, index)
            parts.push(typeExpr(variant, ctx, variantHint))
        })
        const unique = [...new Set(parts)]
        const expr = unique.length ? unique.join(' | ') : 'never'
        return sawNull || nullable ? `${expr} | null` : expr
    }
    if (Array.isArray(schema.allOf)) {
        if (schema.allOf.length === 1) {
            return withNull(typeExpr(schema.allOf[0], ctx, hint))
        }
        const parts = schema.allOf.map((part: JsonSchema, index: number) =>
            parenthesize(typeExpr(part, ctx, `${hint}Part${index + 1}`))
        )
        return withNull(parts.length ? parts.join(' & ') : 'unknown')
    }

    let type = schema.type
    if (Array.isArray(type)) {
        const nonNull = type.filter((t: string) => t !== 'null')
        const hasNull = nonNull.length !== type.length
        const parts = nonNull.map((t: string) => typeExpr({ ...schema, type: t, nullable: false }, ctx, hint))
        const expr = [...new Set(parts)].join(' | ') || 'unknown'
        return hasNull || nullable ? `${expr} | null` : expr
    }
    if (type === undefined) {
        if (schema.properties) {
            type = 'object'
        } else if (schema.items) {
            type = 'array'
        }
    }

    switch (type) {
        case 'string':
            return withNull('string')
        case 'number':
        case 'integer':
            return withNull('number')
        case 'boolean':
            return withNull('boolean')
        case 'null':
            return 'null'
        case 'array': {
            const items = schema.items
            if (Array.isArray(items)) {
                return withNull(
                    `[${items.map((item: JsonSchema, i: number) => typeExpr(item, ctx, `${hint}Item${i + 1}`)).join(', ')}]`
                )
            }
            if (Array.isArray(schema.prefixItems)) {
                return withNull(
                    `[${schema.prefixItems.map((item: JsonSchema, i: number) => typeExpr(item, ctx, `${hint}Item${i + 1}`)).join(', ')}]`
                )
            }
            if (!items || typeof items !== 'object') {
                return withNull('unknown[]')
            }
            return withNull(`${parenthesize(typeExpr(items, ctx, `${hint}Item`))}[]`)
        }
        case 'object': {
            const properties = schema.properties as Record<string, JsonSchema> | undefined
            if (properties && Object.keys(properties).length > 0) {
                return withNull(hoistObject(schema, ctx, hint))
            }
            const additional = schema.additionalProperties
            if (additional && typeof additional === 'object') {
                return withNull(`Record<string, ${typeExpr(additional, ctx, `${hint}Value`)}>`)
            }
            return withNull('Record<string, unknown>')
        }
        default:
            return 'unknown'
    }
}

function variantName(variant: JsonSchema, hint: string, index: number): string {
    if (typeof variant.title === 'string' && isIdentifier(pascal(variant.title))) {
        return `${hint}${pascal(variant.title)}`
    }
    const props = variant.properties as Record<string, JsonSchema> | undefined
    for (const key of ['kind', 'type', 'nodeKind']) {
        const disc = props?.[key]
        const value = disc?.const ?? (Array.isArray(disc?.enum) && disc.enum.length === 1 ? disc.enum[0] : undefined)
        if (typeof value === 'string') {
            return `${hint}${pascal(value)}`
        }
    }
    return `${hint}Variant${index + 1}`
}

/** Hoist an object schema into a named interface, deduplicating structurally identical schemas within the file. */
function hoistObject(schema: JsonSchema, ctx: EmitContext, hint: string): string {
    const { 'x-component': _component, ...structure } = schema
    const key = hashOf(structure)
    const existing = ctx.structural.get(key)
    if (existing) {
        return existing
    }
    // A reshaped copy of a shared entity reads as `<Root>_<Entity>`, so a reader sees which entity it narrows.
    const component = typeof schema['x-component'] === 'string' ? schema['x-component'] : undefined
    const base = component && ctx.currentRoot ? `${ctx.currentRoot}_${component}` : hint
    let name = base
    let suffix = 2
    while (ctx.localDecls.has(name) || ctx.components[name] || ctx.defs[name]) {
        name = `${base}${suffix++}`
    }
    ctx.structural.set(key, name)
    ctx.localDecls.set(name, '') // reserve before recursing so self-references resolve
    ctx.localDecls.set(name, declareNamed(name, schema, ctx, []))
    return name
}

/** Render `export interface Name { ... }` (or `export type Name = ...` for non-objects). */
export function declareNamed(name: string, schema: JsonSchema, ctx: EmitContext, docLines: string[]): string {
    const properties = schema.properties as Record<string, JsonSchema> | undefined
    const isObject =
        (schema.type === 'object' || schema.type === undefined) &&
        properties &&
        !schema.anyOf &&
        !schema.oneOf &&
        !schema.allOf &&
        !schema.$ref
    const doc = renderJsDoc([...docLines, ...docLinesFor(schema).filter((line) => !docLines.includes(line))])
    if (!isObject) {
        const expr = typeExpr(schema, ctx, `${name}Value`)
        return `${doc}export type ${name} = ${expr}\n`
    }
    const required = new Set<string>(Array.isArray(schema.required) ? schema.required : [])
    const lines: string[] = []
    for (const [prop, propSchema] of Object.entries(properties)) {
        const propDoc = renderJsDoc(docLinesFor(propSchema), '    ')
        const optional = required.has(prop) ? '' : '?'
        const expr = typeExpr(propSchema, ctx, `${name}${pascal(prop)}`)
        lines.push(`${propDoc}    ${propertyKey(prop)}${optional}: ${expr}`)
    }
    const additional = schema.additionalProperties
    if (additional && typeof additional === 'object' && Object.keys(additional).length > 0) {
        lines.push(`    [key: string]: ${typeExpr(additional, ctx, `${name}Value`)} | undefined`)
    } else if (additional === true) {
        lines.push(`    [key: string]: unknown`)
    }
    return `${doc}export interface ${name} {\n${lines.join('\n')}\n}\n`
}

// ------------------------------------------------------------------
// Response transforms mirroring services/mcp/src/tools/tool-utils.ts at the schema level
// ------------------------------------------------------------------

export interface TransformContext {
    components: Record<string, JsonSchema>
    /** Component names currently being cloned, to cut recursive schemas. */
    stack: string[]
}

/** Resolve a `$ref` to a deep clone of the component, so edits never touch the shared schema. */
function componentName(schema: JsonSchema): string | undefined {
    return typeof schema.$ref === 'string' && schema.$ref.startsWith(COMPONENT_PREFIX)
        ? schema.$ref.slice(COMPONENT_PREFIX.length)
        : undefined
}

/**
 * Resolve a `$ref` to a deep clone of the component, so edits never touch the shared schema.
 * A component already being transformed higher up the stack (a recursive schema) stays a `$ref`.
 */
function materialize(schema: JsonSchema, tctx: TransformContext): JsonSchema | undefined {
    if (typeof schema.$ref !== 'string') {
        return schema
    }
    const name = componentName(schema)
    if (!name || tctx.stack.includes(name)) {
        return undefined
    }
    const target = tctx.components[name]
    if (!target) {
        return undefined
    }
    // Remember where the clone came from, so a hoisted copy can be named after the entity it reshapes.
    return { ...structuredClone(target), 'x-component': name }
}

/** Run `fn` with the schema's component name on the stack, after `materialize` had its chance to resolve it. */
function withStack<T>(schema: JsonSchema, tctx: TransformContext, fn: () => T): T {
    const name = componentName(schema)
    if (!name) {
        return fn()
    }
    tctx.stack.push(name)
    try {
        return fn()
    } finally {
        tctx.stack.pop()
    }
}

/** Mirror `omitResponseFields`: remove the dot-path (wildcards step into array items / object values). */
export function omitPath(schema: JsonSchema, segments: string[], tctx: TransformContext): JsonSchema {
    if (segments.length === 0) {
        return schema
    }
    const node = materialize(schema, tctx)
    if (!node) {
        return schema
    }
    return withStack(schema, tctx, () => {
        const [head, ...rest] = segments
        if (head === '*') {
            if (node.items && typeof node.items === 'object' && !Array.isArray(node.items)) {
                node.items = omitPath(node.items, rest, tctx)
            } else if (node.additionalProperties && typeof node.additionalProperties === 'object') {
                node.additionalProperties = omitPath(node.additionalProperties, rest, tctx)
            } else if (node.properties) {
                for (const key of Object.keys(node.properties)) {
                    node.properties[key] = omitPath(node.properties[key], rest, tctx)
                }
            }
            return node
        }
        if (Array.isArray(node.anyOf) || Array.isArray(node.oneOf)) {
            const key = Array.isArray(node.anyOf) ? 'anyOf' : 'oneOf'
            node[key] = node[key].map((variant: JsonSchema) => omitPath(variant, segments, tctx))
            return node
        }
        if (!node.properties || !(head! in node.properties)) {
            return node
        }
        if (rest.length === 0) {
            delete node.properties[head!]
            if (Array.isArray(node.required)) {
                node.required = node.required.filter((r: string) => r !== head)
            }
        } else {
            node.properties[head!] = omitPath(node.properties[head!], rest, tctx)
        }
        return node
    })
}

interface PathTrie {
    [segment: string]: PathTrie
}

export function buildTrie(paths: string[]): PathTrie {
    const trie: PathTrie = {}
    for (const p of paths) {
        let node = trie
        for (const segment of p.split('.')) {
            node[segment] ??= {}
            node = node[segment]!
        }
    }
    return trie
}

/** Mirror `pickResponseFields`: keep only the given dot-paths. A leaf keeps its whole subtree. */
export function pickPaths(schema: JsonSchema, trie: PathTrie, tctx: TransformContext): JsonSchema {
    const keys = Object.keys(trie)
    if (keys.length === 0) {
        return schema
    }
    const node = materialize(schema, tctx)
    if (!node) {
        return schema
    }
    return withStack(schema, tctx, () => {
        if (trie['*']) {
            const child = trie['*']
            if (node.items && typeof node.items === 'object' && !Array.isArray(node.items)) {
                node.items = pickPaths(node.items, child, tctx)
                return node
            }
            if (node.additionalProperties && typeof node.additionalProperties === 'object') {
                node.additionalProperties = pickPaths(node.additionalProperties, child, tctx)
                return node
            }
            if (node.properties) {
                for (const key of Object.keys(node.properties)) {
                    node.properties[key] = pickPaths(node.properties[key], child, tctx)
                }
            }
            return node
        }
        if (Array.isArray(node.anyOf) || Array.isArray(node.oneOf)) {
            const key = Array.isArray(node.anyOf) ? 'anyOf' : 'oneOf'
            node[key] = node[key].map((variant: JsonSchema) => pickPaths(variant, trie, tctx))
            return node
        }
        if (!node.properties) {
            return node
        }
        const picked: Record<string, JsonSchema> = {}
        for (const key of keys) {
            if (key in node.properties) {
                picked[key] = pickPaths(node.properties[key], trie[key]!, tctx)
            }
        }
        node.properties = picked
        if (Array.isArray(node.required)) {
            node.required = node.required.filter((r: string) => r in picked)
        }
        delete node.additionalProperties
        return node
    })
}

function allowsNull(schema: JsonSchema): boolean {
    if (schema.nullable === true || schema.type === 'null') {
        return true
    }
    if (Array.isArray(schema.type) && schema.type.includes('null')) {
        return true
    }
    const variants = schema.anyOf ?? schema.oneOf
    return Array.isArray(variants) && variants.some((v: JsonSchema) => isNullSchema(v) || v.nullable === true)
}

function removeNull(schema: JsonSchema): JsonSchema {
    const node = { ...schema }
    delete node.nullable
    if (Array.isArray(node.type)) {
        const rest = node.type.filter((t: string) => t !== 'null')
        node.type = rest.length === 1 ? rest[0] : rest
    }
    for (const key of ['anyOf', 'oneOf'] as const) {
        if (Array.isArray(node[key])) {
            const rest = node[key]
                .filter((v: JsonSchema) => !isNullSchema(v))
                .map((v: JsonSchema) => ({ ...v, nullable: undefined }))
            if (rest.length === 1) {
                const only = rest[0]
                const { [key]: _drop, ...outer } = node
                return {
                    ...only,
                    ...Object.fromEntries(
                        Object.entries(outer).filter(([k]) => k === 'description' || k === 'default')
                    ),
                }
            }
            node[key] = rest
        }
    }
    return node
}

/** Mirror `stripNullFields`: a key whose value is null is removed, so nullable fields become optional non-null. */
export function stripNulls(schema: JsonSchema, tctx: TransformContext): JsonSchema {
    const node = materialize(schema, tctx)
    if (!node) {
        return schema
    }
    return withStack(schema, tctx, () => {
        if (node.items && typeof node.items === 'object' && !Array.isArray(node.items)) {
            node.items = stripNulls(node.items, tctx)
        }
        for (const key of ['anyOf', 'oneOf', 'allOf'] as const) {
            if (Array.isArray(node[key])) {
                node[key] = node[key].map((v: JsonSchema) => stripNulls(v, tctx))
            }
        }
        if (node.additionalProperties && typeof node.additionalProperties === 'object') {
            node.additionalProperties = stripNulls(node.additionalProperties, tctx)
        }
        if (node.properties) {
            const required = new Set<string>(Array.isArray(node.required) ? node.required : [])
            for (const [key, prop] of Object.entries(node.properties as Record<string, JsonSchema>)) {
                let next = prop
                if (allowsNull(prop)) {
                    next = removeNull(prop)
                    required.delete(key)
                }
                node.properties[key] = stripNulls(next, tctx)
            }
            node.required = [...required]
            if (node.required.length === 0) {
                delete node.required
            }
        }
        return node
    })
}

/** Add required string fields (e.g. `_posthogUrl`) to an object schema, materializing a `$ref` first. */
export function addFields(schema: JsonSchema, fields: Record<string, JsonSchema>, tctx: TransformContext): JsonSchema {
    const node = materialize(schema, tctx) ?? { allOf: [schema] }
    if (node.allOf || node.anyOf || node.oneOf || (!node.properties && node.type !== 'object')) {
        return { allOf: [node, { type: 'object', properties: fields, required: Object.keys(fields) }] }
    }
    node.properties = { ...node.properties, ...fields }
    node.required = [...new Set([...(node.required ?? []), ...Object.keys(fields)])]
    return node
}

export function isArraySchema(schema: JsonSchema, tctx: TransformContext): boolean {
    const node = materialize(schema, tctx) ?? schema
    return node.type === 'array'
}
