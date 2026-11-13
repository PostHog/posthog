import { z } from 'zod'

import { ToolDefinitionSchema } from '@/tools/toolDefinitions'

// The catalog format the executor in this build understands. A catalog with any other version is
// ignored whole, so a format change never reaches a CLI that would read it differently.
export const CATALOG_SCHEMA_VERSION = 1

// The oldest hog that may load a catalog this build serves. Raise it when the executor changes in a
// way older CLIs can't detect from the entries themselves.
export const CATALOG_MIN_HOG_VERSION = '0.0.0'

const CAST_HELPERS = ['castStringToInt', 'castBooleanToString', 'castObjectToJsonString'] as const

const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const

const UrlTemplate = z
    .object({
        baseUrl: z.string(),
        joiner: z.enum(['', '/']),
        prefix: z.string(),
        field: z.string(),
        suffix: z.string(),
    })
    .strict()

const Enrichment = z.discriminatedUnion('kind', [
    z.object({ kind: z.literal('list'), baseUrl: z.string() }).strict(),
    UrlTemplate.extend({ kind: z.literal('list_items') }).strict(),
    UrlTemplate.extend({ kind: z.literal('item'), source: z.enum(['result', 'params']) }).strict(),
])

const ResponseFilter = z.discriminatedUnion('kind', [
    z.object({ kind: z.literal('pick'), fields: z.array(z.string()).min(1), selectable: z.boolean() }).strict(),
    z.object({ kind: z.literal('omit'), fields: z.array(z.string()), expandable: z.array(z.string()) }).strict(),
])

export const CatalogHttpToolSchema = z
    .object({
        name: z.string().regex(/^[a-z0-9]+(-[a-z0-9]+)*$/),
        kind: z.literal('http'),
        requires: z.array(z.string()),
        hooks: z.string().nullable(),
        uiApp: z.string().nullable(),
        request: z
            .object({
                method: z.enum(HTTP_METHODS),
                path: z.string().startsWith('/api/'),
                pathParams: z.array(z.string()),
                fallbacks: z.array(z.object({ param: z.string(), scope: z.enum(['projectId', 'orgId']) }).strict()),
                query: z.array(z.object({ param: z.string(), key: z.string(), csv: z.boolean() }).strict()).nullable(),
                body: z.array(z.object({ param: z.string(), key: z.string() }).strict()).nullable(),
                injectBody: z.record(z.string(), z.unknown()),
                softDelete: z.string().nullable(),
                transformBody: z.boolean(),
            })
            .strict(),
        response: z
            .object({
                list: z.boolean(),
                filter: ResponseFilter.nullable(),
                stripNulls: z.boolean(),
                enrich: Enrichment.nullable(),
                agentNote: z.string().nullable(),
                informational: z.object({ tag: z.string(), purpose: z.string().nullable() }).strict().nullable(),
                textInclude: z.array(z.string()),
            })
            .strict(),
        input: z
            .object({
                aliases: z.record(z.string(), z.array(z.string())),
                casts: z.record(z.string(), z.enum(CAST_HELPERS)),
                validators: z.array(z.string()),
            })
            .strict(),
    })
    .strict()

export type CatalogHttpTool = z.infer<typeof CatalogHttpToolSchema>

export const CatalogEntrySchema = CatalogHttpToolSchema.extend({
    definition: ToolDefinitionSchema.strict(),
    inputSchema: z.record(z.string(), z.unknown()),
}).strict()

export type CatalogEntry = z.infer<typeof CatalogEntrySchema>

export const CatalogDocumentSchema = z.object({
    schemaVersion: z.number().int(),
    minHogVersion: z.string(),
    build: z.string().nullable(),
    tools: z.array(z.unknown()),
})

export type CatalogDocument = z.infer<typeof CatalogDocumentSchema>
