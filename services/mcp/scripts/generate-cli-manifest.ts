/**
 * Generates `schema/cli-manifest.json` — the declarative source of truth for the
 * agent CLI (`cli/src/agent`). It is emitted from the same resolved YAML + OpenAPI
 * inputs as the MCP handlers, so the CLI inherits every skip/override/cast/rename
 * automatically and stays in lockstep with the MCP.
 *
 * The manifest is consumed by a generic Rust interpreter that reproduces the MCP's
 * request-shaping byte-for-byte (guarded by the conformance harness). Every
 * transform the MCP applies to build a request is captured here as data, never as
 * code in the runtime.
 */
import type { JsonSchemaRoot } from './lib/json-schema-to-zod'
import type { EnabledQueryWrapperToolConfig, EnabledToolConfig } from './yaml-config-schema'

// ---- Manifest shape (mirror of cli/src/agent/manifest.rs) ----

export interface CliParam {
    name: string
    description?: string
    /** Apply a client-side cast before the value hits the wire (e.g. `string-int`). */
    cast?: string
    /** Send under this wire name instead of `name` (mirrors MCP `rename_params`). */
    rename?: string
    /** Default applied when the caller omits the field (mirrors the MCP schema's zod `.default()`). */
    default?: unknown
    required?: boolean
    type?: string
    /** Scalar, top-level param → exposed as a real `--flag`. Non-eligible params go via `--json`. */
    flag_eligible?: boolean
}

export interface CliToolParams {
    path?: CliParam[]
    query?: CliParam[]
    body?: CliParam[]
}

export interface CliActorsVariant {
    select: string[]
    order_by: string[]
    limit: number
}

export interface CliActorsConfig {
    /**
     * Selected by the runtime `query.source.kind` (mirrors the switch in
     * `query-wrapper-factory.ts` → `client.ts` `runActorsQuery`). Both actors tools
     * share `kind: "InsightActorsQuery"`, so the source kind is the discriminator.
     */
    source_kind_map: Record<string, CliActorsVariant>
    include_recordings_field?: string
    recordings_select?: string
}

export interface CliQueryWrapper {
    kind: string
    actors?: CliActorsConfig
}

export interface CliTool {
    mcp_name: string
    category: string
    verb: string
    description?: string
    method: string
    path: string
    scopes: string[]
    annotations: { read_only: boolean; destructive: boolean; idempotent: boolean }
    params: CliToolParams
    soft_delete?: boolean | string
    inject_body?: Record<string, string | number | boolean>
    /** State key to resolve a param from when omitted (`projectId` | `orgId`). */
    fallbacks?: Record<string, string>
    query_wrapper?: CliQueryWrapper
    enrich_url?: string
    response_include?: string[]
}

// ---- Types we borrow structurally from generate-tools.ts ----

interface ResolvedOp {
    method: string
    path: string
    operation: {
        parameters?: Array<{
            in: string
            name: string
            required?: boolean
            schema?: { type?: string }
            description?: string
        }>
        summary?: string
        description?: string
    }
}

interface Composition {
    pathParamNames: string[]
    queryParamNames: string[]
    bodyFieldNames: string[]
    renamedFields: Record<string, string>
    paramFallbacks: Record<string, string>
}

interface Helpers {
    composeToolSchema: (config: EnabledToolConfig, resolved: ResolvedOp) => Composition
    resolveDescription: (
        config: { description?: string; description_file?: string },
        yamlDir: string,
        fallback: string
    ) => string
    extractKindFromSchemaRef: (querySchema: JsonSchemaRoot, schemaRef: string) => string
    /** Top-level body-field metadata (default + scalar type + description) from the OpenAPI request schema, keyed by wire name. */
    bodyMeta: (resolved: ResolvedOp) => Record<string, { default?: unknown; type?: string; description?: string }>
}

export interface CategoryBundle {
    /** `feature` is unused for naming now; `category` is the human display name we slugify. */
    config: { feature: string; category: string }
    enabledTools: [string, EnabledToolConfig, ResolvedOp][]
    enabledWrappers: [string, EnabledQueryWrapperToolConfig][]
    yamlDir: string
}

/**
 * Actors-query request shaping. Mirrors the per-source-kind constants in
 * `services/mcp/src/api/client.ts` (`runActorsQuery` callers). Each actors tool
 * has a fixed `kind`, so this maps the wrapper kind → the select/orderBy/limit the
 * MCP applies. THIS IS THE ONE TRANSFORM NOT DERIVED FROM CONFIG — it lives in
 * handwritten MCP code, so it is mirrored here and guarded by the conformance harness.
 */
const ACTORS_SOURCE_MAP: Record<string, CliActorsVariant> = {
    TrendsQuery: { select: ['actor', 'event_count'], order_by: ['event_count DESC', 'actor_id DESC'], limit: 100 },
    LifecycleQuery: { select: ['actor'], order_by: [], limit: 100 },
}

function actorsConfigForKind(kind: string): CliActorsConfig | undefined {
    if (!kind.endsWith('ActorsQuery')) {
        return undefined
    }
    return {
        source_kind_map: ACTORS_SOURCE_MAP,
        include_recordings_field: 'includeRecordings',
        recordings_select: 'matched_recordings',
    }
}

const SCALAR_TYPES = new Set(['string', 'integer', 'number', 'boolean'])

function singularize(word: string): string {
    if (word.endsWith('ies')) {
        return `${word.slice(0, -3)}y`
    }
    if (word.endsWith('ses')) {
        return word.slice(0, -2)
    }
    if (word.endsWith('s') && !word.endsWith('ss')) {
        return word.slice(0, -1)
    }
    return word
}

/** Human category name → command slug, e.g. "Feature flags" → "feature-flag". */
function categorySlug(display: string): string {
    const parts = display
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .split('-')
        .filter(Boolean)
    if (parts.length === 0) {
        return 'misc'
    }
    parts[parts.length - 1] = singularize(parts[parts.length - 1]!)
    return parts.join('-')
}

/** Tool name → verb under its category, stripping the category words. e.g. ("create-feature-flag","feature-flag") → "create". */
const VERB_ALIASES: Record<string, string> = {
    'get-all': 'list',
}

function deriveVerb(mcpName: string, slug: string): string {
    // Remove the full slug, its plural, and individual long tokens, so e.g. "feature-flag-get-all" → "get-all".
    const tokens = slug.split('-').filter((t) => t.length >= 4)
    const variants = [slug, `${slug}s`, ...tokens, ...tokens.map((t) => `${t}s`)]
    let verb = mcpName
    for (const variant of variants) {
        verb = verb.replace(new RegExp(`(^|-)${variant}(?=-|$)`, 'g'), '')
    }
    verb = verb.replace(/^-+|-+$/g, '').replace(/-+/g, '-')
    verb = verb || mcpName
    return VERB_ALIASES[verb] ?? verb
}

function buildParam(
    name: string,
    location: 'path' | 'query' | 'body',
    config: EnabledToolConfig,
    resolved: ResolvedOp,
    renamedFields: Record<string, string>,
    bodyMeta: Record<string, { default?: unknown; type?: string; description?: string }>
): CliParam {
    const param: CliParam = { name }

    const override = config.param_overrides?.[name]
    if (override?.cast) {
        param.cast = override.cast
    }

    // Body field aliases map back to the original wire name.
    const wire = renamedFields[name]
    if (wire) {
        param.rename = wire
    }

    if (location === 'body') {
        const meta = bodyMeta[wire ?? name]
        // Only OpenAPI body-field defaults are live (param_overrides defaults are `.default().optional()`,
        // which zod's optional short-circuits — verified by the activity-log-list expected request).
        if (meta?.default !== undefined) {
            param.default = meta.default
        }
        if (typeof meta?.type === 'string') {
            param.type = meta.type
        }
        if (meta?.description) {
            param.description = meta.description
        }
    }

    if (location === 'path') {
        param.required = true
    }

    // Type/required/description from the OpenAPI parameter for path & query.
    if (location !== 'body') {
        const op = resolved.operation.parameters?.find((p) => p.name === name && p.in === location)
        if (op) {
            // OpenAPI `type` can be an array (nullable unions); only carry the simple string form.
            if (typeof op.schema?.type === 'string') {
                param.type = op.schema.type
            }
            if (location === 'query') {
                param.required = Boolean(op.required)
            }
            if (op.description) {
                param.description = op.description
            }
        }
    }

    // Flag-eligible = scalar, top-level. Path params are always scalar; complex body/query
    // params (objects/arrays, or unknown type) go through --json.
    if (location === 'path' || (param.type !== undefined && SCALAR_TYPES.has(param.type))) {
        param.flag_eligible = true
    }

    return param
}

export function generateCliManifest(
    categories: CategoryBundle[],
    querySchema: JsonSchemaRoot,
    helpers: Helpers
): Record<string, CliTool> {
    const manifest: Record<string, CliTool> = {}
    const { composeToolSchema, resolveDescription, extractKindFromSchemaRef, bodyMeta } = helpers

    // Track verbs per category slug so two tools never collide on `<category> <verb>`.
    const usedVerbs = new Map<string, Set<string>>()
    const assignVerb = (slug: string, mcpName: string): string => {
        let verb = deriveVerb(mcpName, slug)
        let used = usedVerbs.get(slug)
        if (!used) {
            used = new Set()
            usedVerbs.set(slug, used)
        }
        if (used.has(verb)) {
            verb = mcpName // globally-unique fallback on collision
        }
        used.add(verb)
        return verb
    }

    for (const { config: category, enabledTools, enabledWrappers, yamlDir } of categories) {
        const slug = categorySlug(category.category)

        // REST tools
        for (const [name, config, resolved] of enabledTools) {
            const composition = composeToolSchema(config, resolved)
            const isSoftDelete = config.soft_delete !== undefined && config.soft_delete !== false
            const bodyMetaMap = bodyMeta(resolved)

            const params: CliToolParams = {}
            const pathParams = composition.pathParamNames.map((n) =>
                buildParam(n, 'path', config, resolved, composition.renamedFields, bodyMetaMap)
            )
            const queryParams = composition.queryParamNames.map((n) =>
                buildParam(n, 'query', config, resolved, composition.renamedFields, bodyMetaMap)
            )
            const bodyParams = composition.bodyFieldNames.map((n) =>
                buildParam(n, 'body', config, resolved, composition.renamedFields, bodyMetaMap)
            )
            if (pathParams.length) {
                params.path = pathParams
            }
            if (queryParams.length) {
                params.query = queryParams
            }
            if (bodyParams.length) {
                params.body = bodyParams
            }

            const description = resolveDescription(config, yamlDir, resolved.operation.summary ?? '')
            const tool: CliTool = {
                mcp_name: name,
                category: slug,
                verb: assignVerb(slug, name),
                ...(description ? { description } : {}),
                method: isSoftDelete ? 'PATCH' : resolved.method,
                path: resolved.path,
                scopes: config.scopes,
                annotations: {
                    read_only: config.annotations.readOnly,
                    destructive: config.annotations.destructive,
                    idempotent: config.annotations.idempotent,
                },
                params,
            }

            if (isSoftDelete && config.soft_delete !== undefined) {
                tool.soft_delete = config.soft_delete
            }
            if (config.inject_body && Object.keys(config.inject_body).length > 0) {
                tool.inject_body = config.inject_body
            }
            if (Object.keys(composition.paramFallbacks).length > 0) {
                tool.fallbacks = composition.paramFallbacks
            }
            if (config.enrich_url) {
                tool.enrich_url = config.enrich_url
            }
            if (config.response?.include?.length) {
                tool.response_include = config.response.include
            }

            manifest[name] = tool
        }

        // Query wrapper tools
        for (const [name, wrapperConfig] of enabledWrappers) {
            const kind = extractKindFromSchemaRef(querySchema, wrapperConfig.schema_ref)
            const queryWrapper: CliQueryWrapper = { kind }
            const actors = actorsConfigForKind(kind)
            if (actors) {
                queryWrapper.actors = actors
            }

            manifest[name] = {
                mcp_name: name,
                category: slug,
                verb: assignVerb(slug, name),
                method: 'POST',
                path: '/api/environments/{project_id}/query/',
                scopes: wrapperConfig.scopes,
                annotations: {
                    read_only: wrapperConfig.annotations.readOnly,
                    destructive: wrapperConfig.annotations.destructive,
                    idempotent: wrapperConfig.annotations.idempotent,
                },
                params: {},
                query_wrapper: queryWrapper,
                ...(wrapperConfig.url_prefix ? { enrich_url: wrapperConfig.url_prefix } : {}),
            }
        }
    }

    // Sort keys for stable diffs.
    return Object.fromEntries(Object.entries(manifest).sort(([a], [b]) => a.localeCompare(b)))
}
