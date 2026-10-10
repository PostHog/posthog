/**
 * SDK prototype generator: emits grep-friendly TypeScript interfaces for every tool in the
 * CLI/MCP catalog. Inputs come from each tool's Zod schema (the same JSON Schema `exec info`
 * serves); outputs come from the OpenAPI response schema with the tool's YAML response
 * transforms (include/exclude/strip_nulls, list envelope, enrichment) applied at the schema level.
 *
 * Run with `pnpm --filter=@posthog/mcp exec tsx scripts/sdk/run.ts` (esbuild bundles the catalog). Output dir: $SDK_OUT.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { parse as parseYaml } from 'yaml'
import { z } from 'zod'

import { preprocessSchema } from '../../../../tools/openapi-codegen/src/preprocess.mjs'
import { getCliTools } from '../../src/cli/tools'
import { getToolDefinition } from '../../src/tools/toolDefinitions'
import type { Tool, ZodObjectAny } from '../../src/tools/types'
import { discoverDefinitions, isQueryWrappersConfig } from '../lib/definitions.mjs'
import { CategoryConfigSchema, QueryWrappersConfigSchema } from '../yaml-config-schema'
import {
    addFields,
    buildTrie,
    declareNamed,
    type EmitContext,
    isArraySchema,
    type JsonSchema,
    omitPath,
    pascal,
    pickPaths,
    renderJsDoc,
    stripNulls,
    type TransformContext,
    typeExpr,
} from './json-schema-to-ts'

const MCP_ROOT = process.cwd()
const REPO_ROOT = path.resolve(MCP_ROOT, '../..')
const OUT_DIR = process.env.SDK_OUT ?? path.resolve(MCP_ROOT, 'dist/sdk-prototype')
const OPENAPI_PATH = path.resolve(REPO_ROOT, 'frontend/tmp/openapi.json')
const QUERY_SCHEMA_PATH = path.resolve(REPO_ROOT, 'frontend/src/queries/schema.json')

type AnyConfig = Record<string, any>

interface YamlTool {
    kind: 'rest'
    module: string
    yamlPath: string
    category: AnyConfig
    config: AnyConfig
    /** Set for the two tools a `confirmed_action` entry expands into. */
    confirmedRole?: 'prepare' | 'execute'
}

interface YamlWrapper {
    kind: 'wrapper'
    module: string
    yamlPath: string
    category: AnyConfig
    config: AnyConfig
}

interface ResolvedOperation {
    method: string
    path: string
    operation: AnyConfig
}

interface ToolRecord {
    name: string
    pascal: string
    module: string
    kind: 'rest' | 'wrapper' | 'handwritten'
    title: string
    description: string
    category: string
    feature: string
    scopes: string[]
    annotations: Tool['annotations']
    source: string
    inputSchema: JsonSchema
    output: {
        schema?: JsonSchema
        text?: string
        notes: string[]
        typed: 'schema' | 'override' | 'wrapper' | 'prepare' | 'unknown'
    }
}

// ------------------------------------------------------------------
// Catalog loading
// ------------------------------------------------------------------

function loadYamlIndex(): { tools: Map<string, YamlTool>; wrappers: Map<string, YamlWrapper> } {
    const tools = new Map<string, YamlTool>()
    const wrappers = new Map<string, YamlWrapper>()
    const sources = discoverDefinitions({
        definitionsDir: path.resolve(MCP_ROOT, 'definitions'),
        productsDir: path.resolve(REPO_ROOT, 'products'),
    }) as { moduleName: string; filePath: string }[]
    for (const source of sources) {
        const parsed = parseYaml(fs.readFileSync(source.filePath, 'utf-8'))
        const yamlPath = path.relative(REPO_ROOT, source.filePath)
        if (isQueryWrappersConfig(parsed)) {
            const config = QueryWrappersConfigSchema.parse(parsed) as AnyConfig
            for (const [name, wrapper] of Object.entries(config.wrappers as Record<string, AnyConfig>)) {
                if (wrapper.enabled) {
                    wrappers.set(name, {
                        kind: 'wrapper',
                        module: source.moduleName,
                        yamlPath,
                        category: config,
                        config: wrapper,
                    })
                }
            }
            continue
        }
        const config = CategoryConfigSchema.parse(parsed) as AnyConfig
        for (const [name, tool] of Object.entries((config.tools ?? {}) as Record<string, AnyConfig>)) {
            if (!tool.enabled) {
                continue
            }
            const base: YamlTool = { kind: 'rest', module: source.moduleName, yamlPath, category: config, config: tool }
            if (tool.confirmed_action) {
                tools.set(`${name}-prepare`, { ...base, confirmedRole: 'prepare' })
                tools.set(`${name}-execute`, { ...base, confirmedRole: 'execute' })
            } else {
                tools.set(name, base)
            }
        }
        for (const [name, wrapper] of Object.entries((config.wrappers ?? {}) as Record<string, AnyConfig>)) {
            if (wrapper.enabled) {
                wrappers.set(name, {
                    kind: 'wrapper',
                    module: source.moduleName,
                    yamlPath,
                    category: config,
                    config: wrapper,
                })
            }
        }
    }
    return { tools, wrappers }
}

/** Same lookup as generate-tools.ts: exact operationId first, preferring /api/projects/ paths. */
function findOperation(spec: AnyConfig, operationId: string): ResolvedOperation | undefined {
    const base = operationId.replace(/_\d+$/, '')
    let exactFallback: ResolvedOperation | undefined
    let baseFallback: ResolvedOperation | undefined
    let baseProject: ResolvedOperation | undefined
    for (const [urlPath, methods] of Object.entries(spec.paths as Record<string, Record<string, AnyConfig>>)) {
        for (const [method, op] of Object.entries(methods)) {
            if (!op?.operationId) {
                continue
            }
            const resolved = { method: method.toUpperCase(), path: urlPath, operation: op }
            if (op.operationId === operationId) {
                if (urlPath.startsWith('/api/projects/')) {
                    return resolved
                }
                exactFallback ??= resolved
                continue
            }
            if (op.operationId.replace(/_\d+$/, '') !== base) {
                continue
            }
            if (urlPath.startsWith('/api/projects/')) {
                baseProject ??= resolved
            } else {
                baseFallback ??= resolved
            }
        }
    }
    return exactFallback ?? baseProject ?? baseFallback
}

function responseSchemaOf(operation: AnyConfig): JsonSchema | undefined {
    for (const status of ['200', '201']) {
        const schema = operation.responses?.[status]?.content?.['application/json']?.schema
        if (schema) {
            return schema
        }
    }
    return undefined
}

const STRING_FIELD: JsonSchema = { type: 'string' }
const POSTHOG_URL_FIELD = { _posthogUrl: { ...STRING_FIELD, description: 'Link to this object in the PostHog app.' } }
const AGENT_NOTE_FIELD = {
    _agentNote: { ...STRING_FIELD, description: 'Point-of-use guidance for the calling agent. Not data.' },
}

function wrapArray(items: JsonSchema, extra: Record<string, JsonSchema>): JsonSchema {
    return { type: 'object', properties: { results: items, ...extra }, required: ['results', ...Object.keys(extra)] }
}

function materializeObject(schema: JsonSchema, tctx: TransformContext): JsonSchema | undefined {
    if (typeof schema.$ref === 'string') {
        const name = schema.$ref.replace('#/components/schemas/', '')
        return tctx.components[name] ? structuredClone(tctx.components[name]) : undefined
    }
    return schema
}

/** Apply the YAML `response` transforms, list envelope and enrichments to an operation's response schema. */
function restOutput(
    yamlTool: YamlTool,
    resolved: ResolvedOperation,
    spec: AnyConfig,
    components: Record<string, JsonSchema>
): ToolRecord['output'] {
    const config = yamlTool.config
    const notes: string[] = []
    const tctx: TransformContext = { components, stack: [] }
    let operation = resolved.operation
    const isSoftDelete = config.soft_delete !== undefined && config.soft_delete !== false
    if (isSoftDelete) {
        operation = spec.paths[resolved.path]?.patch ?? operation
        notes.push('Soft delete: the request is a PATCH, so the response is the updated object.')
    }
    if (config.response_type) {
        const text = String(config.response_type).replace(/\bSchemas\./g, '')
        notes.push(`Response type declared in YAML as \`${config.response_type}\`.`)
        return { text, notes, typed: 'override' }
    }
    const response = responseSchemaOf(operation)
    if (!response) {
        notes.push(`The API declares no JSON response body for ${resolved.method} ${resolved.path}.`)
        return { notes, typed: 'unknown' }
    }
    const responseFilter = config.response ?? {}
    const hasFilter = Boolean(
        responseFilter.include?.length || responseFilter.exclude?.length || responseFilter.strip_nulls
    )
    const applyItem = (schema: JsonSchema): JsonSchema => {
        let shaped = schema
        if (responseFilter.include?.length) {
            shaped = pickPaths(shaped, buildTrie(responseFilter.include), tctx)
            if (responseFilter.selectable) {
                const node = materializeObject(shaped, tctx)
                if (node) {
                    delete node.required
                    shaped = node
                }
                notes.push('`fields` narrows the response to a subset of these keys, so every key is optional.')
            }
        } else if (responseFilter.exclude?.length) {
            for (const p of responseFilter.exclude as string[]) {
                shaped = omitPath(shaped, p.split('.'), tctx)
            }
        }
        if (responseFilter.strip_nulls) {
            shaped = stripNulls(shaped, tctx)
        }
        return shaped
    }
    const isArray = isArraySchema(response, tctx)
    let shaped: JsonSchema = response
    if (config.list) {
        if (hasFilter) {
            if (isArray) {
                notes.push(
                    'list + response filter on an array response: the generated handler maps `result.results`, which an array does not have.'
                )
            } else {
                const node = materializeObject(shaped, tctx)
                const results = node?.properties?.results
                if (node && results?.items) {
                    node.properties.results = { ...results, items: applyItem(results.items) }
                    shaped = node
                }
            }
        }
        if (config.enrich_url) {
            if (isArray) {
                const node = materializeObject(shaped, tctx)!
                shaped = { ...node, items: addFields(node.items, POSTHOG_URL_FIELD, tctx) }
            } else {
                const node = materializeObject(shaped, tctx)
                const results = node?.properties?.results
                if (node && results?.items) {
                    node.properties.results = { ...results, items: addFields(results.items, POSTHOG_URL_FIELD, tctx) }
                    shaped = node
                }
            }
        }
        shaped = isArraySchema(shaped, tctx)
            ? wrapArray(shaped, POSTHOG_URL_FIELD)
            : addFields(shaped, POSTHOG_URL_FIELD, tctx)
    } else {
        if (hasFilter) {
            shaped = applyItem(shaped)
        }
        if (config.enrich_url) {
            shaped = isArraySchema(shaped, tctx)
                ? wrapArray(shaped, POSTHOG_URL_FIELD)
                : addFields(shaped, POSTHOG_URL_FIELD, tctx)
        }
    }
    if (config.agent_note) {
        shaped = isArraySchema(shaped, tctx)
            ? wrapArray(shaped, AGENT_NOTE_FIELD)
            : addFields(shaped, AGENT_NOTE_FIELD, tctx)
        notes.push(`@agentNote ${String(config.agent_note).trim()}`)
    }
    if (responseFilter.informational_wrapper) {
        notes.push(
            `@informational ${responseFilter.informational_wrapper.tag}: ${responseFilter.informational_wrapper.purpose ?? ''}`.trim()
        )
    }
    if (responseFilter.text_include?.length) {
        notes.push(`@textProjection ${responseFilter.text_include.join(', ')}`)
    }
    return { schema: shaped, notes, typed: 'schema' }
}

function wrapperOutput(wrapper: YamlWrapper, defs: Record<string, JsonSchema>): ToolRecord['output'] {
    const notes: string[] = []
    const schemaRef = wrapper.config.schema_ref as string
    const def = defs[schemaRef]
    const kind = def?.properties?.kind?.const as string | undefined
    if (!kind) {
        notes.push(`schema.json definition ${schemaRef} has no \`kind\` const.`)
        return { notes, typed: 'unknown' }
    }
    if (kind.endsWith('ActorsQuery')) {
        notes.push('Actors query: the API response plus a link to the matching data table.')
        return { text: `ActorsQueryResponse & { _posthogUrl: string }`, notes, typed: 'wrapper' }
    }
    const baseDef = defs[schemaRef.replace(/^Assistant/, '')]
    const responseRef = baseDef?.properties?.response?.$ref as string | undefined
    const responseDef = responseRef ? defs[responseRef.replace('#/definitions/', '')] : undefined
    const resultsSchema = responseDef?.properties?.results
    notes.push(
        `Response rows from ${responseRef ? responseRef.replace('#/definitions/', '') : 'an undeclared response type'}; the handler returns the rows, the query it sent and any warnings, not the whole API response.`
    )
    if (['TraceQuery', 'TracesQuery'].includes(kind)) {
        notes.push('`detail: "summary"` returns compacted rows; the type describes `detail: "full"`.')
    }
    return {
        text: `__WRAPPER__`,
        schema: resultsSchema,
        notes,
        typed: resultsSchema ? 'wrapper' : 'unknown',
    }
}

// ------------------------------------------------------------------
// Emission
// ------------------------------------------------------------------

function newEmitContext(components: Record<string, JsonSchema>, defs: Record<string, JsonSchema>): EmitContext {
    return {
        components,
        defs,
        localDecls: new Map(),
        structural: new Map(),
        sharedUsed: new Set(),
        queryDefsUsed: new Set(),
    }
}

function toolDocLines(record: ToolRecord, which: 'Input' | 'Output'): string[] {
    const flags = [
        record.annotations.readOnlyHint ? 'read-only' : 'writes',
        record.annotations.destructiveHint ? 'destructive (requires confirm)' : '',
        record.annotations.idempotentHint ? 'idempotent' : '',
    ].filter(Boolean)
    const lines = [`${which} of tool \`${record.name}\`: ${record.title}`, '']
    if (which === 'Input') {
        lines.push(record.description.trim(), '')
    }
    lines.push(
        `@tool ${record.name}`,
        `@scopes ${record.scopes.length ? record.scopes.join(', ') : '(none)'}`,
        `@flags ${flags.join(', ')}`
    )
    if (which === 'Output') {
        lines.push(...record.output.notes)
    }
    return lines
}

function emitModule(
    moduleName: string,
    records: ToolRecord[],
    components: Record<string, JsonSchema>,
    defs: Record<string, JsonSchema>
): { code: string; ctx: EmitContext; runtimeImports: Set<string> } {
    const ctx = newEmitContext(components, defs)
    const runtimeImports = new Set<string>()
    const chunks: string[] = []
    const mapEntries: string[] = []
    for (const record of records.sort((a, b) => a.name.localeCompare(b.name))) {
        const inputName = `${record.pascal}Input`
        const outputName = `${record.pascal}Output`
        ctx.currentRoot = inputName
        chunks.push(
            declareNamed(
                inputName,
                record.inputSchema,
                { ...ctx, root: record.inputSchema },
                toolDocLines(record, 'Input')
            )
        )
        ctx.currentRoot = outputName
        const outputDoc = renderJsDoc(toolDocLines(record, 'Output'))
        const out = record.output
        if (out.typed === 'prepare') {
            runtimeImports.add('PrepareConfirmedActionResult')
            chunks.push(`${outputDoc}export type ${outputName} = PrepareConfirmedActionResult\n`)
        } else if (out.text === '__WRAPPER__') {
            runtimeImports.add('QueryWarning')
            const results = out.schema ? typeExpr(out.schema, ctx, `${outputName}Results`) : 'unknown'
            const kindConst = (record as ToolRecord & { queryKind?: string }).queryKind ?? 'unknown'
            chunks.push(
                `${outputDoc}export interface ${outputName} {\n` +
                    `    /** Link to this query in the PostHog app. */\n    _posthogUrl: string\n` +
                    `    /** The query as sent to the API, with \`kind\` filled in. */\n    query: ${inputName} & { kind: ${JSON.stringify(kindConst)} }\n` +
                    `    results: ${results}\n` +
                    `    warnings?: QueryWarning[]\n}\n`
            )
        } else if (out.text) {
            for (const match of out.text.matchAll(/\b([A-Z][A-Za-z0-9_]*)\b/g)) {
                if (components[match[1]!]) {
                    ctx.sharedUsed.add(match[1]!)
                } else if (defs[match[1]!]) {
                    ctx.queryDefsUsed.add(match[1]!)
                }
            }
            chunks.push(`${outputDoc}export type ${outputName} = ${out.text}\n`)
        } else if (out.schema) {
            chunks.push(declareNamed(outputName, out.schema, ctx, toolDocLines(record, 'Output')))
        } else {
            chunks.push(`${outputDoc}export type ${outputName} = unknown\n`)
        }
        mapEntries.push(
            `    /** ${record.title.replace(/\*\//g, '*\\/')} */\n    ${JSON.stringify(record.name)}: { input: ${inputName}; output: ${outputName} }`
        )
    }
    const hoisted = [...ctx.localDecls.values()].filter(Boolean)
    const imports: string[] = []
    if (ctx.sharedUsed.size) {
        imports.push(`import type { ${[...ctx.sharedUsed].sort().join(', ')} } from '../entities'`)
    }
    if (ctx.queryDefsUsed.size) {
        imports.push(`import type { ${[...ctx.queryDefsUsed].sort().join(', ')} } from '../queries'`)
    }
    if (runtimeImports.size) {
        imports.push(`import type { ${[...runtimeImports].sort().join(', ')} } from '../runtime-types'`)
    }
    const header = `// AUTO-GENERATED by services/mcp/scripts/sdk/generate.ts from the MCP tool catalog — do not edit.\n// Tools in this file: ${records
        .map((r) => r.name)
        .sort()
        .join(', ')}\n`
    const code = `${header}${imports.length ? `${imports.join('\n')}\n\n` : '\n'}${chunks.join('\n')}\n${hoisted.length ? `${hoisted.join('\n')}\n` : ''}export interface ${pascal(moduleName)}Tools {\n${mapEntries.join('\n')}\n}\n`
    return { code, ctx, runtimeImports }
}

function collectRefs(schema: unknown, prefix: string, into: Set<string>): void {
    if (!schema || typeof schema !== 'object') {
        return
    }
    if (Array.isArray(schema)) {
        schema.forEach((item) => collectRefs(item, prefix, into))
        return
    }
    const node = schema as JsonSchema
    if (typeof node.$ref === 'string' && node.$ref.startsWith(prefix)) {
        into.add(node.$ref.slice(prefix.length))
    }
    for (const value of Object.values(node)) {
        collectRefs(value, prefix, into)
    }
}

function closure(names: Set<string>, registry: Record<string, JsonSchema>, prefix: string): string[] {
    const all = new Set(names)
    const queue = [...names]
    while (queue.length) {
        const name = queue.shift()!
        const found = new Set<string>()
        collectRefs(registry[name], prefix, found)
        for (const ref of found) {
            if (!all.has(ref)) {
                all.add(ref)
                queue.push(ref)
            }
        }
    }
    return [...all].sort()
}

function emitSharedFile(
    title: string,
    names: string[],
    registry: Record<string, JsonSchema>,
    components: Record<string, JsonSchema>,
    defs: Record<string, JsonSchema>,
    importQueries: boolean
): string {
    const ctx = newEmitContext(components, defs)
    for (const name of names) {
        ctx.localDecls.set(name, '')
    }
    for (const name of names) {
        const schema = registry[name]
        ctx.localDecls.set(name, schema ? declareNamed(name, schema, ctx, []) : `export type ${name} = unknown\n`)
    }
    const decls = [...ctx.localDecls.values()].filter(Boolean)
    const imports =
        importQueries && ctx.queryDefsUsed.size
            ? `import type { ${[...ctx.queryDefsUsed].sort().join(', ')} } from './queries'\n\n`
            : ''
    return `// AUTO-GENERATED by services/mcp/scripts/sdk/generate.ts — ${title}. Do not edit.\n\n${imports}${decls.join('\n')}`
}

const RUNTIME_TYPES = `// AUTO-GENERATED by services/mcp/scripts/sdk/generate.ts — shapes the MCP runtime adds around API responses.

/** Result of a \`*-prepare\` tool: relay \`message\` to the user, then call \`*-execute\` with the hash once they type the confirmation word. */
export interface PrepareConfirmedActionResult {
    confirmation_hash: string
    confirmation_word: 'confirm'
    action: string
    message: string
    /** Hint for the model. Surfaces as text on the tool result. */
    next_steps: string
}

export interface DataWarehouseSyncWarning {
    type: 'warehouse_sync'
    table_name: string
    schema_name: string
    source_type: string
    status: string
    message: string
}

export interface AccessControlFilterWarning {
    type: 'access_control'
    resources: string[]
    message: string
}

export type QueryWarning = DataWarehouseSyncWarning | AccessControlFilterWarning
`

// ------------------------------------------------------------------
// Main
// ------------------------------------------------------------------

function main(): void {
    const spec = preprocessSchema(JSON.parse(fs.readFileSync(OPENAPI_PATH, 'utf-8'))) as AnyConfig
    const components = spec.components.schemas as Record<string, JsonSchema>
    const defs = (
        JSON.parse(fs.readFileSync(QUERY_SCHEMA_PATH, 'utf-8')) as { definitions: Record<string, JsonSchema> }
    ).definitions
    const yaml = loadYamlIndex()
    const tools = getCliTools({ aiConsentGiven: true }) as Tool<ZodObjectAny>[]

    const records: ToolRecord[] = []
    const problems: string[] = []
    for (const tool of tools) {
        const definition = getToolDefinition(tool.name)
        const inputSchema = (tool.rawInputSchema ??
            z.toJSONSchema(tool.schema, { io: 'input', reused: 'inline' })) as JsonSchema
        const base: Omit<ToolRecord, 'module' | 'kind' | 'source' | 'output'> = {
            name: tool.name,
            pascal: pascal(tool.name),
            title: tool.title,
            description: tool.description,
            category: definition.category,
            feature: definition.feature,
            scopes: tool.scopes,
            annotations: tool.annotations,
            inputSchema,
        }
        const yamlTool = yaml.tools.get(tool.name)
        const wrapper = yaml.wrappers.get(tool.name)
        if (yamlTool) {
            const resolved = findOperation(spec, yamlTool.config.operation)
            if (!resolved) {
                problems.push(`${tool.name}: operation ${yamlTool.config.operation} not found`)
                records.push({
                    ...base,
                    module: yamlTool.module,
                    kind: 'rest',
                    source: yamlTool.yamlPath,
                    output: { notes: ['operation not found'], typed: 'unknown' },
                })
                continue
            }
            const output =
                yamlTool.confirmedRole === 'prepare'
                    ? { notes: [], typed: 'prepare' as const }
                    : restOutput(yamlTool, resolved, spec, components)
            records.push({ ...base, module: yamlTool.module, kind: 'rest', source: yamlTool.yamlPath, output })
        } else if (wrapper) {
            const output = wrapperOutput(wrapper, defs)
            const record: ToolRecord & { queryKind?: string } = {
                ...base,
                module: wrapper.module,
                kind: 'wrapper',
                source: wrapper.yamlPath,
                output,
            }
            record.queryKind = defs[wrapper.config.schema_ref]?.properties?.kind?.const
            records.push(record)
        } else {
            records.push({
                ...base,
                module: 'handwritten',
                kind: 'handwritten',
                source: 'services/mcp/src/tools/',
                output: {
                    notes: [
                        'Hand-written tool: its result type is declared in code, not in YAML, and is not lifted yet.',
                    ],
                    typed: 'unknown',
                },
            })
        }
    }

    fs.rmSync(OUT_DIR, { recursive: true, force: true })
    fs.mkdirSync(path.join(OUT_DIR, 'src/tools'), { recursive: true })

    const byModule = new Map<string, ToolRecord[]>()
    for (const record of records) {
        byModule.set(record.module, [...(byModule.get(record.module) ?? []), record])
    }
    const sharedUsed = new Set<string>()
    const queryDefsUsed = new Set<string>()
    const moduleFiles: { module: string; file: string; chars: number; tools: number }[] = []
    for (const [moduleName, moduleRecords] of [...byModule.entries()].sort(([a], [b]) => a.localeCompare(b))) {
        const { code, ctx } = emitModule(moduleName, moduleRecords, components, defs)
        const file = `src/tools/${moduleName}.ts`
        fs.writeFileSync(path.join(OUT_DIR, file), code)
        ctx.sharedUsed.forEach((name) => sharedUsed.add(name))
        ctx.queryDefsUsed.forEach((name) => queryDefsUsed.add(name))
        moduleFiles.push({ module: moduleName, file, chars: code.length, tools: moduleRecords.length })
    }

    const entityNames = closure(sharedUsed, components, '#/components/schemas/')
    const entitiesCode = emitSharedFile(
        'shared API entities referenced by tool outputs',
        entityNames,
        components,
        components,
        defs,
        false
    )
    fs.writeFileSync(path.join(OUT_DIR, 'src/entities.ts'), entitiesCode)
    const queryNames = closure(queryDefsUsed, defs, '#/definitions/')
    const queriesCode = emitSharedFile(
        'query response types from frontend/src/queries/schema.json',
        queryNames,
        defs,
        {},
        defs,
        false
    )
    fs.writeFileSync(path.join(OUT_DIR, 'src/queries.ts'), queriesCode)
    fs.writeFileSync(path.join(OUT_DIR, 'src/runtime-types.ts'), RUNTIME_TYPES)

    const modules = [...byModule.keys()].sort()
    const index =
        `// AUTO-GENERATED by services/mcp/scripts/sdk/generate.ts — do not edit.\n` +
        modules.map((m) => `import type { ${pascal(m)}Tools } from './tools/${m}'`).join('\n') +
        `\n\n/** Every tool name mapped to its input and output types. Grep a tool name in this file to find its types. */\n` +
        `export interface ToolMap extends ${modules.map((m) => `${pascal(m)}Tools`).join(', ')} {}\n\n` +
        `export type ToolName = keyof ToolMap\nexport type ToolInput<N extends ToolName> = ToolMap[N]['input']\nexport type ToolOutput<N extends ToolName> = ToolMap[N]['output']\n\n` +
        modules.map((m) => `export type * from './tools/${m}'`).join('\n') +
        `\nexport type * from './entities'\nexport type * as Queries from './queries'\nexport type * as Runtime from './runtime-types'\nexport { TOOL_META } from './meta'\n`
    fs.writeFileSync(path.join(OUT_DIR, 'src/index.ts'), index)

    const metaEntries = records
        .sort((a, b) => a.name.localeCompare(b.name))
        .map(
            (r) =>
                `    ${JSON.stringify(r.name)}: { title: ${JSON.stringify(r.title)}, category: ${JSON.stringify(r.category)}, feature: ${JSON.stringify(r.feature)}, scopes: ${JSON.stringify(r.scopes)}, readOnly: ${r.annotations.readOnlyHint}, destructive: ${r.annotations.destructiveHint}, idempotent: ${r.annotations.idempotentHint}, kind: ${JSON.stringify(r.kind)}, types: ${JSON.stringify(`tools/${r.module}`)}, source: ${JSON.stringify(r.source)} },`
        )
    const meta = `// AUTO-GENERATED by services/mcp/scripts/sdk/generate.ts — do not edit.\nimport type { ToolName } from './index'\n\nexport interface ToolMeta {\n    title: string\n    category: string\n    feature: string\n    scopes: readonly string[]\n    readOnly: boolean\n    destructive: boolean\n    idempotent: boolean\n    kind: 'rest' | 'wrapper' | 'handwritten'\n    /** Module under src/ that declares this tool's Input and Output interfaces. */\n    types: string\n    /** Where the tool is defined in the PostHog repo. */\n    source: string\n}\n\nexport const TOOL_META = {\n${metaEntries.join('\n')}\n} as const satisfies Record<ToolName, ToolMeta>\n`
    fs.writeFileSync(path.join(OUT_DIR, 'src/meta.ts'), meta)

    const catalog =
        `# PostHog SDK tool catalog\n\nOne line per tool. Types live in \`src/tools/<module>.ts\` as \`<ToolPascal>Input\` and \`<ToolPascal>Output\`.\n\n| Tool | Title | Kind | Types | Scopes | Flags |\n| --- | --- | --- | --- | --- | --- |\n` +
        records
            .sort((a, b) => a.name.localeCompare(b.name))
            .map(
                (r) =>
                    `| \`${r.name}\` | ${r.title.replace(/\|/g, '\\|')} | ${r.kind} | \`tools/${r.module}#${r.pascal}Input\` | ${r.scopes.join(', ')} | ${[r.annotations.readOnlyHint ? 'read' : 'write', r.annotations.destructiveHint ? 'destructive' : ''].filter(Boolean).join(', ')} |`
            )
            .join('\n') +
        '\n'
    fs.writeFileSync(path.join(OUT_DIR, 'CATALOG.md'), catalog)

    fs.writeFileSync(
        path.join(OUT_DIR, 'tsconfig.json'),
        JSON.stringify(
            {
                compilerOptions: {
                    strict: true,
                    noEmit: true,
                    target: 'es2022',
                    module: 'esnext',
                    moduleResolution: 'bundler',
                    skipLibCheck: true,
                    isolatedModules: true,
                    verbatimModuleSyntax: true,
                },
                include: ['src/**/*.ts'],
            },
            null,
            2
        )
    )

    const inputChars = records.reduce((sum, r) => sum + JSON.stringify(r.inputSchema).length, 0)
    const typed: Record<string, number> = {}
    const kinds: Record<string, number> = {}
    for (const r of records) {
        typed[r.output.typed] = (typed[r.output.typed] ?? 0) + 1
        kinds[r.kind] = (kinds[r.kind] ?? 0) + 1
    }
    const stats = {
        tools: records.length,
        modules: modules.length,
        kinds,
        outputTyping: typed,
        entities: entityNames.length,
        queryDefs: queryNames.length,
        inputJsonSchemaChars: inputChars,
        toolFileChars: moduleFiles.reduce((sum, m) => sum + m.chars, 0),
        entitiesChars: entitiesCode.length,
        queriesChars: queriesCode.length,
        largestModules: moduleFiles.sort((a, b) => b.chars - a.chars).slice(0, 8),
        problems,
        listFilterOnArray: records
            .filter((r) => r.output.notes.some((n) => n.startsWith('list + response filter')))
            .map((r) => r.name),
        untypedRest: records.filter((r) => r.kind === 'rest' && r.output.typed === 'unknown').map((r) => r.name),
        handwritten: records.filter((r) => r.kind === 'handwritten').map((r) => r.name),
    }
    fs.writeFileSync(path.join(OUT_DIR, 'stats.json'), JSON.stringify(stats, null, 2))
}

main()
