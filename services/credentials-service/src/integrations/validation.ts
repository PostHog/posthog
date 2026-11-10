// Request shapes of `/v1/integrations/*`. Every body is a strict object, so a field the service
// does not know (an `owner` or a `team_id`, say) fails validation instead of being ignored.

import { z } from 'zod'

import type { ConfigValue, SourceRows } from '../db/integration-queries'
import { type IntegrationRef, parseIntegrationRef } from '../db/integrations'
import { IntegrationApiError } from './errors'

export const MAX_BATCH_REFS = 200
export const DEFAULT_PAGE_SIZE = 100
export const MAX_PAGE_SIZE = 1000

/** The auth types of `posthog/integrations/enums.py`. The provider registry narrows them per kind. */
export const AUTH_TYPES = ['oauth', 'token', 'credentials'] as const
export type AuthType = (typeof AUTH_TYPES)[number]

const KIND = /^[a-z0-9][a-z0-9_-]{0,63}$/
// The config key rule of the Python SDK accessors: one plain JSON key, no Django lookup separator.
const CONFIG_KEY = /^[A-Za-z][A-Za-z0-9_]{0,99}$/
// The service stores these as columns, so a filter on the config copy would be wrong.
const RESERVED_CONFIG_KEYS: ReadonlySet<string> = new Set(['auth_type', 'warehouse_source_type'])
const IDEMPOTENCY_KEY = /^[\x21-\x7e]{1,200}$/
const MAX_EXTERNAL_ID_LENGTH = 400
const MAX_ERRORS_LENGTH = 10_000
const MAX_VERSION = 2_147_483_647

function isConfigKey(key: string): boolean {
    return CONFIG_KEY.test(key) && !key.includes('__') && !RESERVED_CONFIG_KEYS.has(key)
}

const kind = z.string().regex(KIND, 'must be a lowercase kind name')
const externalId = z.string().min(1).max(MAX_EXTERNAL_ID_LENGTH)
const configKey = z.string().refine(isConfigKey, 'is not a config key the service can filter on')
const jsonObject = z.record(z.string(), z.json())
const keyList = z.array(z.string().min(1).max(200)).max(200)
const teamIds = z.array(z.int().positive()).max(10_000)
const configValue = z.union([z.string(), z.number(), z.boolean(), z.null()])
const configInValue = z.union([z.string(), z.number(), z.boolean()])
const ref = z.string().refine((value) => parseIntegrationRef(value) !== null, 'must be a legacy id or a UUID')
const refList = z.array(ref).min(1).max(MAX_BATCH_REFS)
const sourceRows = z.enum(['exclude', 'only', 'include'])
const iexactPath = z
    .string()
    .refine((path) => path.split('.').length <= 2 && path.split('.').every(isConfigKey), 'is not a config path')

export const newIntegrationBody = z.strictObject({
    kind,
    integration_id: externalId.nullable(),
    auth_type: z.string(),
    config: jsonObject.default({}),
    sensitive_config: jsonObject.default({}),
    created_by_id: z.int().positive().nullable().default(null),
    is_source_row: z.boolean().default(false),
})
export type NewIntegrationBody = z.infer<typeof newIntegrationBody>

export const patchBody = z.strictObject({
    config_patch: jsonObject.default({}),
    config_remove: keyList.default([]),
    sensitive_config_patch: jsonObject.default({}),
    sensitive_config_remove: keyList.default([]),
    errors: z.string().max(MAX_ERRORS_LENGTH).nullable().default(null),
})
export type PatchBody = z.infer<typeof patchBody>

export const refsBody = z.strictObject({ refs: refList })

export const crossTeamBody = z.strictObject({
    kinds: z.array(kind).min(1).max(200),
    auth_types: z.array(z.string()).min(1).max(AUTH_TYPES.length).nullable().default(null),
    source_rows: sourceRows.default('exclude'),
    team_ids: teamIds.nullable().default(null),
    exclude_team_ids: teamIds.default([]),
    created_by_ids: teamIds.nullable().default(null),
    external_id: externalId.nullable().default(null),
    where: z.record(configKey, configValue).default({}),
    where_in: z.record(configKey, z.array(configInValue).max(1000)).default({}),
    where_iexact: z.record(iexactPath, z.string().max(1000)).default({}),
    has_config_key: configKey.nullable().default(null),
    newest_first: z.boolean().default(false),
    limit: z.int().min(1).max(MAX_PAGE_SIZE).default(MAX_PAGE_SIZE),
    after: z.string().nullable().default(null),
})
export type CrossTeamBody = z.infer<typeof crossTeamBody>

function validationError(error: z.ZodError): IntegrationApiError {
    // Paths and messages only: an issue never carries the rejected value back to the caller.
    const issues = error.issues.map((issue) => ({ path: issue.path.join('.'), message: issue.message }))
    return new IntegrationApiError('validation', 'the request is not valid', { issues })
}

export function parse<T extends z.ZodType>(schema: T, input: unknown): z.infer<T> {
    const result = schema.safeParse(input)
    if (!result.success) {
        throw validationError(result.error)
    }
    return result.data
}

export function checkAuthType(value: string): AuthType {
    const authType = AUTH_TYPES.find((known) => known === value)
    if (!authType) {
        throw new IntegrationApiError('unsupported_auth_type', 'the auth type is not supported', {
            auth_type: value,
        })
    }
    return authType
}

export function parseRef(value: string): IntegrationRef {
    const parsed = parseIntegrationRef(value)
    if (!parsed) {
        throw new IntegrationApiError('validation', 'the ref must be a legacy id or a UUID', { ref: value })
    }
    return parsed
}

/** Reads `If-Match`: a version number, bare or quoted as an ETag. Null when the header is absent. */
export function parseIfMatch(header: string | undefined): number | null {
    if (header === undefined) {
        return null
    }
    const match = /^\s*(?:"([1-9]\d{0,9})"|([1-9]\d{0,9}))\s*$/.exec(header)
    const version = Number(match?.[1] ?? match?.[2] ?? Number.NaN)
    // `version` is a Postgres integer column.
    if (!Number.isSafeInteger(version) || version > MAX_VERSION) {
        throw new IntegrationApiError('validation', 'If-Match must be a version number')
    }
    return version
}

export function parseIdempotencyKey(header: string | undefined): string | null {
    if (header === undefined) {
        return null
    }
    if (!IDEMPOTENCY_KEY.test(header)) {
        throw new IntegrationApiError('validation', 'Idempotency-Key must be 1 to 200 printable ASCII characters')
    }
    return header
}

export interface ListQuery {
    kinds: string[] | null
    authTypes: string[] | null
    externalId: string | null
    where: Record<string, ConfigValue>
    sourceRows: SourceRows
    limit: number
    newestFirst: boolean
    after: string | null
}

/**
 * Reads the query string of `GET /`. `kind` and `auth_type` repeat. Each `where.<key>` value is
 * JSON, so `where.region="us"` and `where.count=3` compare with the JSON type, the same as the SDK.
 */
export function parseListQuery(params: Record<string, string[]>): ListQuery {
    const issues: { path: string; message: string }[] = []
    const single = (name: string): string | null => {
        const values = params[name]
        if (!values || values.length === 0) {
            return null
        }
        if (values.length > 1) {
            issues.push({ path: name, message: 'must appear at most once' })
        }
        return values[0] ?? null
    }

    const kinds = params['kind'] ?? null
    for (const value of kinds ?? []) {
        if (!KIND.test(value)) {
            issues.push({ path: 'kind', message: 'must be a lowercase kind name' })
        }
    }
    const authTypes = params['auth_type'] ?? null

    const where: Record<string, ConfigValue> = {}
    for (const [name, values] of Object.entries(params)) {
        if (!name.startsWith('where.')) {
            continue
        }
        const key = name.slice('where.'.length)
        if (!isConfigKey(key)) {
            issues.push({ path: name, message: 'is not a config key the service can filter on' })
            continue
        }
        if (values.length !== 1) {
            issues.push({ path: name, message: 'must appear once' })
            continue
        }
        const parsed = configValue.safeParse(parseJson(values[0] ?? ''))
        if (!parsed.success) {
            issues.push({ path: name, message: 'must be a JSON string, number, boolean or null' })
            continue
        }
        where[key] = parsed.data
    }

    const sourceRowsValue = single('source_rows') ?? 'exclude'
    const parsedSourceRows = sourceRows.safeParse(sourceRowsValue)
    if (!parsedSourceRows.success) {
        issues.push({ path: 'source_rows', message: 'must be exclude, only or include' })
    }

    const limitValue = single('limit')
    const limit = limitValue === null ? DEFAULT_PAGE_SIZE : Number(limitValue)
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_PAGE_SIZE) {
        issues.push({ path: 'limit', message: `must be an integer from 1 to ${MAX_PAGE_SIZE}` })
    }

    const newestFirstValue = single('newest_first')
    if (newestFirstValue !== null && newestFirstValue !== 'true' && newestFirstValue !== 'false') {
        issues.push({ path: 'newest_first', message: 'must be true or false' })
    }

    const externalIdValue = single('external_id')
    const after = single('after')

    for (const name of Object.keys(params)) {
        if (!name.startsWith('where.') && !LIST_PARAMS.has(name)) {
            issues.push({ path: name, message: 'is not a known filter' })
        }
    }

    if (issues.length > 0) {
        throw new IntegrationApiError('validation', 'the request is not valid', { issues })
    }
    return {
        kinds,
        authTypes,
        externalId: externalIdValue,
        where,
        sourceRows: parsedSourceRows.data ?? 'exclude',
        limit,
        newestFirst: newestFirstValue === 'true',
        after,
    }
}

const LIST_PARAMS: ReadonlySet<string> = new Set([
    'kind',
    'auth_type',
    'external_id',
    'source_rows',
    'limit',
    'newest_first',
    'after',
])

function parseJson(text: string): unknown {
    try {
        return JSON.parse(text)
    } catch {
        return undefined
    }
}

export const MAX_CHANGES_PAGE_SIZE = 500
export const DEFAULT_CHANGES_PAGE_SIZE = 100

/** Reads query parameters, and collects every problem into one `validation` error. */
class QueryReader {
    readonly issues: { path: string; message: string }[] = []

    constructor(
        private readonly params: Record<string, string[]>,
        private readonly known: readonly string[]
    ) {}

    issue(path: string, message: string): void {
        this.issues.push({ path, message })
    }

    single(name: string): string | null {
        const values = this.params[name]
        if (!values || values.length === 0) {
            return null
        }
        if (values.length > 1) {
            this.issue(name, 'must appear at most once')
        }
        return values[0] ?? null
    }

    list(name: string): string[] | null {
        return this.params[name] ?? null
    }

    int(name: string, fallback: number, min: number, max: number): number {
        const text = this.single(name)
        const value = text === null ? fallback : Number(text)
        if (!Number.isSafeInteger(value) || value < min || value > max) {
            this.issue(name, `must be an integer from ${min} to ${max}`)
        }
        return value
    }

    finish(): void {
        for (const name of Object.keys(this.params)) {
            if (!this.known.includes(name)) {
                this.issue(name, 'is not a known parameter')
            }
        }
        if (this.issues.length > 0) {
            throw new IntegrationApiError('validation', 'the request is not valid', { issues: this.issues })
        }
    }
}

function readSourceRows(reader: QueryReader): SourceRows {
    const parsed = sourceRows.safeParse(reader.single('source_rows') ?? 'exclude')
    if (!parsed.success) {
        reader.issue('source_rows', 'must be exclude, only or include')
    }
    return parsed.data ?? 'exclude'
}

export interface ExternalIdTarget {
    kind: string
    externalId: string
}

/** The `:kind` and `:external_id` path segments of the cross-team routes. */
export function parseExternalIdTarget(kindText: string, externalIdText: string): ExternalIdTarget {
    const parsed = parse(z.strictObject({ kind, external_id: externalId }), {
        kind: kindText,
        external_id: externalIdText,
    })
    return { kind: parsed.kind, externalId: parsed.external_id }
}

export interface ExternalIdListQuery {
    teamIds: number[] | null
    sourceRows: SourceRows
    limit: number
    after: string | null
}

/** `GET /by-external-id/:kind/:external_id`: `team_id` (repeats), `source_rows`, `limit` and `after`. */
export function parseExternalIdListQuery(params: Record<string, string[]>): ExternalIdListQuery {
    const reader = new QueryReader(params, ['team_id', 'source_rows', 'limit', 'after'])
    const teamIdTexts = reader.list('team_id')
    const teamIds = teamIdTexts === null ? null : teamIdTexts.map(Number)
    if (teamIds?.some((id) => !Number.isSafeInteger(id) || id < 1)) {
        reader.issue('team_id', 'must be a positive integer')
    }
    const result = {
        teamIds,
        sourceRows: readSourceRows(reader),
        limit: reader.int('limit', MAX_PAGE_SIZE, 1, MAX_PAGE_SIZE),
        after: reader.single('after'),
    }
    reader.finish()
    return result
}

/** `PATCH` and `DELETE /by-external-id/:kind/:external_id`: only `source_rows`. */
export function parseExternalIdWriteQuery(params: Record<string, string[]>): { sourceRows: SourceRows } {
    const reader = new QueryReader(params, ['source_rows'])
    const result = { sourceRows: readSourceRows(reader) }
    reader.finish()
    return result
}

export interface ChangesQuery {
    kinds: string[] | null
    since: string | null
    limit: number
}

/** `GET /changes`: `kind` (repeats), `since` (the `next` of the last page) and `limit`. */
export function parseChangesQuery(params: Record<string, string[]>): ChangesQuery {
    const reader = new QueryReader(params, ['kind', 'since', 'limit'])
    const kinds = reader.list('kind')
    for (const value of kinds ?? []) {
        if (!KIND.test(value)) {
            reader.issue('kind', 'must be a lowercase kind name')
        }
    }
    const result = {
        kinds,
        since: reader.single('since'),
        limit: reader.int('limit', DEFAULT_CHANGES_PAGE_SIZE, 1, MAX_CHANGES_PAGE_SIZE),
    }
    reader.finish()
    return result
}

/** `DELETE /?owner=<team id>`. */
export function parseOwnerQuery(params: Record<string, string[]>): { ownerId: number } {
    const reader = new QueryReader(params, ['owner'])
    const text = reader.single('owner')
    const ownerId = text === null ? Number.NaN : Number(text)
    if (!Number.isSafeInteger(ownerId) || ownerId < 1) {
        reader.issue('owner', 'must be a positive team id')
    }
    reader.finish()
    return { ownerId }
}
