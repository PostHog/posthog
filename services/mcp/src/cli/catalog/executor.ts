import { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import { type UiAppKey, URI_MAP } from '@/resources/ui-apps.generated'
import * as toolInputs from '@/schema/tool-inputs'
import {
    castBooleanToString,
    castObjectToJsonString,
    castStringToInt,
    normalizeParamAliases,
} from '@/tools/cast-helpers'
import { GENERATED_TOOL_HOOKS } from '@/tools/generated/hooks'
import { type ToolHooks, transformRequestBody, withToolHooks } from '@/tools/tool-hooks'
import {
    omitResponseFields,
    pickResponseFields,
    stripNullFields,
    withAgentNote,
    withInformationalResponse,
    withPostHogUrl,
    withTextProjection,
} from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

import type { CatalogEntry, CatalogHttpTool } from './schema'

const CASTS: Record<CatalogHttpTool['input']['casts'][string], (value: unknown) => unknown> = {
    castStringToInt,
    castBooleanToString,
    castObjectToJsonString,
}

type Params = Record<string, unknown>

function hasKey(target: object, key: string): boolean {
    return Object.prototype.hasOwnProperty.call(target, key)
}

type Validator = (value: unknown, ctx: z.RefinementCtx) => void

function validatorNamed(name: string): Validator | undefined {
    const candidate = (toolInputs as Record<string, unknown>)[name]
    return typeof candidate === 'function' ? (candidate as Validator) : undefined
}

export function hasCapability(capability: string): boolean {
    if (capability.startsWith('hook:')) {
        return hasKey(GENERATED_TOOL_HOOKS, capability.slice('hook:'.length))
    }
    if (capability.startsWith('validator:')) {
        return validatorNamed(capability.slice('validator:'.length)) !== undefined
    }
    return false
}

export function hasUiApp(appKey: string): appKey is UiAppKey {
    return hasKey(URI_MAP, appKey)
}

function readPath(target: unknown, path: string): unknown {
    return target === null || target === undefined ? undefined : (target as Record<string, unknown>)[path]
}

type JsonSchemaNode = Record<string, unknown>

function resolveRef(node: JsonSchemaNode, root: JsonSchemaNode): JsonSchemaNode {
    const ref = node['$ref']
    if (typeof ref !== 'string') {
        return node
    }
    const name = ref.split('/').pop() ?? ''
    const defs = (root['$defs'] ?? root['definitions']) as Record<string, JsonSchemaNode> | undefined
    return defs?.[name] ?? node
}

const branchSchemas = new WeakMap<JsonSchemaNode, z.ZodType>()

function branchSchema(node: JsonSchemaNode, root: JsonSchemaNode): z.ZodType {
    let schema = branchSchemas.get(node)
    if (!schema) {
        const defs = root['$defs'] ? { $defs: root['$defs'] } : {}
        schema = z.fromJSONSchema({ ...defs, ...node } as Parameters<typeof z.fromJSONSchema>[0])
        branchSchemas.set(node, schema)
    }
    return schema
}

// z.fromJSONSchema drops a `default` on an `enum` or `const` field, so a field the compiled tool
// fills in would go out missing. Defaults are filled here instead, wherever the schema gives one.
// In a union, the branch is the first one that validates once its own defaults are filled, which
// is the branch the compiled zod union picks.
function withDefaults(node: JsonSchemaNode, value: unknown, root: JsonSchemaNode, depth = 0): unknown {
    const schema = resolveRef(node, root)
    if (depth > 16 || value === null || value === undefined) {
        return value
    }

    const branches = (schema['anyOf'] ?? schema['oneOf']) as JsonSchemaNode[] | undefined
    if (branches) {
        for (const branch of branches) {
            const filled = withDefaults(branch, value, root, depth + 1)
            if (branchSchema(resolveRef(branch, root), root).safeParse(filled).success) {
                return filled
            }
        }
        return value
    }
    if (typeof value !== 'object') {
        return value
    }
    if (Array.isArray(value)) {
        const items = schema['items']
        return items && typeof items === 'object'
            ? value.map((item) => withDefaults(items as JsonSchemaNode, item, root, depth + 1))
            : value
    }

    const properties = schema['properties'] as Record<string, JsonSchemaNode> | undefined
    if (!properties) {
        return value
    }
    const copy: Params = { ...(value as Params) }
    for (const [key, property] of Object.entries(properties)) {
        const resolved = resolveRef(property, root)
        if (copy[key] === undefined && hasKey(resolved, 'default')) {
            copy[key] = structuredClone(resolved['default'])
        }
        if (copy[key] !== undefined) {
            copy[key] = withDefaults(resolved, copy[key], root, depth + 1)
        }
    }
    return copy
}

// Casts and aliases run before validation, as the generated z.preprocess wrappers do: aliases on the
// whole input first, then each cast on its own field.
function buildSchema(entry: CatalogEntry): ZodObjectAny {
    let schema: z.ZodType = z.fromJSONSchema(entry.inputSchema as Parameters<typeof z.fromJSONSchema>[0])
    for (const name of entry.input.validators) {
        const validator = validatorNamed(name)
        if (validator) {
            schema = schema.superRefine(validator)
        }
    }

    const aliases = Object.keys(entry.input.aliases).length > 0 ? normalizeParamAliases(entry.input.aliases) : null
    const casts = Object.entries(entry.input.casts)
    const root = entry.inputSchema

    return z.preprocess((input) => {
        const normalized = aliases ? aliases(input) : input
        if (normalized === null || typeof normalized !== 'object' || Array.isArray(normalized)) {
            return normalized
        }
        const copy: Params = { ...(normalized as Params) }
        for (const [param, cast] of casts) {
            if (hasKey(copy, param)) {
                copy[param] = CASTS[cast](copy[param])
            }
        }
        return withDefaults(root, copy, root)
    }, schema)
}

function buildRequest(
    entry: CatalogEntry,
    params: Params,
    ids: { projectId: unknown; orgId: unknown },
    locals: Params
): { method: string; path: string; query?: Params } {
    const { request } = entry
    let path = request.path
        .replace('{project_id}', encodeURIComponent(String(ids.projectId)))
        .replace('{organization_id}', encodeURIComponent(String(ids.orgId)))
    for (const param of request.pathParams) {
        const value = hasKey(locals, param) ? locals[param] : params[param]
        path = path.replace(`{${param}}`, encodeURIComponent(String(value)))
    }

    if (!request.query) {
        return { method: request.method, path }
    }
    const query: Params = {}
    for (const { param, key, csv } of request.query) {
        const value = params[param]
        query[key] = csv && Array.isArray(value) ? value.join(',') || undefined : value
    }
    return { method: request.method, path, query }
}

async function shapeResponse(entry: CatalogEntry, context: Context, params: Params, result: unknown): Promise<unknown> {
    const { response } = entry

    let shapeItem = (target: unknown): unknown => target
    if (response.filter?.kind === 'pick') {
        const { fields, selectable } = response.filter
        const requested = params['fields']
        const paths = selectable && Array.isArray(requested) && requested.length ? (requested as string[]) : fields
        shapeItem = (target) => pickResponseFields(target, paths)
    } else if (response.filter?.kind === 'omit') {
        const expand = params['expand']
        const paths = [
            ...response.filter.fields,
            ...response.filter.expandable.filter((path) => !(Array.isArray(expand) && expand.includes(path))),
        ]
        shapeItem = (target) => omitResponseFields(target, paths)
    }
    if (response.stripNulls) {
        const inner = shapeItem
        shapeItem = (target) => stripNullFields(inner(target))
    }

    let value = result
    if (response.filter || response.stripNulls) {
        value = response.list
            ? {
                  ...(result as Params),
                  results: ((readPath(result, 'results') as unknown[] | undefined) ?? []).map((item) =>
                      shapeItem(item)
                  ),
              }
            : shapeItem(result)
    }

    const enrich = response.enrich
    if (enrich?.kind === 'list_items') {
        const page = value as Params
        const items = (readPath(page, 'results') as unknown[] | undefined) ?? []
        value = await withPostHogUrl(
            context,
            {
                ...page,
                results: await Promise.all(
                    items.map((item) =>
                        withPostHogUrl(
                            context,
                            item,
                            `${enrich.baseUrl}${enrich.joiner}${enrich.prefix}${readPath(item, enrich.field)}${enrich.suffix}`
                        )
                    )
                ),
            },
            enrich.baseUrl
        )
    } else if (enrich?.kind === 'list') {
        value = await withPostHogUrl(context, value, enrich.baseUrl)
    } else if (enrich?.kind === 'item') {
        const source = enrich.source === 'params' ? params[enrich.field] : readPath(value, enrich.field)
        value = await withPostHogUrl(
            context,
            value,
            `${enrich.baseUrl}${enrich.joiner}${enrich.prefix}${source}${enrich.suffix}`
        )
    }

    if (response.agentNote !== null) {
        value = withAgentNote(value, response.agentNote)
    }
    if (response.informational) {
        value =
            response.informational.purpose !== null
                ? withInformationalResponse(value, response.informational.tag, response.informational.purpose)
                : withInformationalResponse(value, response.informational.tag)
    }
    if (response.textInclude.length) {
        value = withTextProjection(value, response.textInclude)
    }
    return value
}

export function catalogTool(entry: CatalogEntry): ToolBase<ZodObjectAny> {
    const hooks: ToolHooks<Params> | undefined = entry.hooks ? GENERATED_TOOL_HOOKS[entry.hooks] : undefined
    const { request } = entry

    const handler = async (context: Context, params: Params): Promise<unknown> => {
        const orgId = request.path.includes('{organization_id}') ? await context.stateManager.getOrgID() : undefined
        const projectId = request.path.includes('{project_id}') ? await context.stateManager.getProjectId() : undefined

        const locals: Params = {}
        for (const { param, scope } of request.fallbacks) {
            const value =
                params[param] ??
                (scope === 'orgId' ? await context.stateManager.getOrgID() : await context.stateManager.getProjectId())
            if (!value) {
                throw new Error(
                    `${param} is required. Provide it explicitly or set an active ${scope === 'orgId' ? 'organization' : 'project'} first.`
                )
            }
            locals[param] = value
        }

        let body: Params | undefined
        if (request.body) {
            body = {}
            for (const { param, key } of request.body) {
                if (hasKey(locals, param)) {
                    body[key] = locals[param]
                } else if (params[param] !== undefined) {
                    body[key] = params[param]
                }
            }
            for (const [key, value] of Object.entries(request.injectBody)) {
                body[key] = value
            }
        }

        const { method, path, query } = buildRequest(entry, params, { projectId, orgId }, locals)
        const requestBody =
            request.softDelete !== null
                ? { [request.softDelete]: true }
                : request.transformBody && hooks && body
                  ? await transformRequestBody(hooks, context, params, body)
                  : body
        const result = await context.api.request<unknown>({
            method: method as 'GET',
            path,
            ...(requestBody !== undefined ? { body: requestBody } : {}),
            ...(query !== undefined ? { query } : {}),
        })
        return shapeResponse(entry, context, params, result)
    }

    const tool: ToolBase<ZodObjectAny> = {
        name: entry.name,
        schema: buildSchema(entry),
        handler: hooks ? withToolHooks(hooks, handler) : handler,
    }
    return entry.uiApp && hasUiApp(entry.uiApp) ? withUiApp(entry.uiApp, tool) : tool
}
