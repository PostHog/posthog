import { z } from 'zod'

import { PostHogApiError, ToolInputValidationError } from '@/lib/errors'
import { castStringToInt, normalizeParamAliases } from '@/tools/cast-helpers'
import { truncateText } from '@/tools/posthogAiTools/externalDataSourcesJobs'
import type { Context, ToolBase } from '@/tools/types'

const DEFAULT_LIMIT = 100
const MESSAGE_MAX_LENGTH = 1000
const MAX_FANOUT_SCHEMAS = 10
const MAX_JOB_IDS_PER_GROUP = 5

// PostHog ids are UUIDTs whose version/variant nibbles don't follow RFC 4122, so `z.uuid()`
// (which enforces those nibbles in Zod 4) rejects valid ids — e.g. a `0` version nibble. Use
// `z.guid()`, which accepts any 8-4-4-4-12 hex string.
const schema = z.preprocess(
    normalizeParamAliases({ schema_id: ['id', 'schemaId', 'table_id'], source_id: ['sourceId'] }),
    z.object({
        schema_id: z
            .guid()
            .optional()
            .describe(
                'UUID of the table (schema) to get sync logs for, from external-data-schemas-list or the `schemas` ' +
                    'of external-data-sources-retrieve. This is not the source id. Pass this or source_id.'
            ),
        source_id: z
            .guid()
            .optional()
            .describe(
                `UUID of a data warehouse source. Reads the logs of its failed or syncing tables (up to ${MAX_FANOUT_SCHEMAS}, ` +
                    'failed tables first) and merges them. Pass this or schema_id.'
            ),
        job_id: z
            .guid()
            .optional()
            .describe(
                'Optional workflow_run_id to filter logs for a specific sync job. Get this from external-data-sources-jobs.'
            ),
        level: z
            .enum(['DEBUG', 'INFO', 'WARNING', 'ERROR'])
            .optional()
            .describe('Minimum log level to return. Defaults to INFO (excludes DEBUG).'),
        search: z
            .string()
            .optional()
            .describe('Search string to filter log messages (case-insensitive substring match).'),
        since: z
            .string()
            .optional()
            .describe(
                'ISO 8601 timestamp. Only return entries after it (e.g. "2025-01-01T00:00:00Z"). Defaults to 7 days ago.'
            ),
        until: z.string().optional().describe('ISO 8601 timestamp. Only return entries before it.'),
        limit: z
            .preprocess(castStringToInt, z.number().int().min(1).max(500))
            .optional()
            .describe(
                `Max number of raw log entries to read per table (default ${DEFAULT_LIMIT}), newest first. Also caps the rows returned.`
            ),
        dedupe: z
            .boolean()
            .optional()
            .describe(
                'Group repeated messages into one row with count, first_seen and last_seen (default true). ' +
                    'Set to false for the raw entries.'
            ),
    })
)

type Params = z.infer<typeof schema>

const LEVEL_ORDER = ['DEBUG', 'INFO', 'WARNING', 'ERROR'] as const

interface LogEntry {
    instance_id: string
    timestamp: string
    level: string
    message: string
}

interface LogEntryPage {
    count?: number
    results?: LogEntry[]
}

interface SchemaRef {
    id: string
    name: string
}

export interface SyncLogGroup {
    level: string
    /** The newest message of the group, cut to MESSAGE_MAX_LENGTH characters. */
    message: string
    count: number
    first_seen: string
    last_seen: string
    job_ids: string[]
    table?: string
}

export interface SyncLogEntry {
    timestamp: string
    level: string
    message: string
    job_id: string
    table?: string
}

export interface SyncLogsResult {
    /** The tables read, when called with source_id. */
    tables?: SchemaRef[]
    /** Entries that match the filters, read or not. */
    total_matching: number
    entries_read: number
    /** True when more entries match than were read or returned. Narrow with since/until, level or job_id. */
    has_more: boolean
    groups?: SyncLogGroup[]
    entries?: SyncLogEntry[]
    note?: string
}

/** Ids, numbers and hex strings vary between repeats of one error, so they are left out of the group key. */
export function normalizeLogMessage(message: string): string {
    return message
        .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '<id>')
        .replace(/\b(?=[0-9a-f]*\d)[0-9a-f]{8,}\b/gi, '<hex>')
        .replace(/\d+(\.\d+)?/g, '<n>')
        .replace(/\s+/g, ' ')
        .trim()
}

type TaggedEntry = LogEntry & { table?: string }

/** ISO strings with and without fractional seconds do not sort as text, so compare the parsed times. */
function timeOf(timestamp: string): number {
    const time = Date.parse(timestamp)
    return Number.isNaN(time) ? 0 : time
}

const newestFirst = (a: string, b: string): number => timeOf(b) - timeOf(a)

/** Entries arrive newest first, so the first entry of a group is its newest. */
export function dedupeLogEntries(entries: TaggedEntry[]): SyncLogGroup[] {
    const groups = new Map<string, SyncLogGroup>()
    for (const entry of entries) {
        const key = `${entry.table ?? ''}\u0000${entry.level}\u0000${normalizeLogMessage(entry.message)}`
        const group = groups.get(key)
        if (!group) {
            groups.set(key, {
                level: entry.level,
                message: truncateText(entry.message, MESSAGE_MAX_LENGTH),
                count: 1,
                first_seen: entry.timestamp,
                last_seen: entry.timestamp,
                job_ids: entry.instance_id ? [entry.instance_id] : [],
                ...(entry.table ? { table: entry.table } : {}),
            })
            continue
        }
        group.count += 1
        if (timeOf(entry.timestamp) < timeOf(group.first_seen)) {
            group.first_seen = entry.timestamp
        }
        if (timeOf(entry.timestamp) > timeOf(group.last_seen)) {
            group.last_seen = entry.timestamp
        }
        if (
            entry.instance_id &&
            group.job_ids.length < MAX_JOB_IDS_PER_GROUP &&
            !group.job_ids.includes(entry.instance_id)
        ) {
            group.job_ids.push(entry.instance_id)
        }
    }
    return [...groups.values()].sort((a, b) => newestFirst(a.last_seen, b.last_seen))
}

function projectPath(projectId: string | number): string {
    return `/api/projects/${encodeURIComponent(String(projectId))}`
}

async function isSourceId(context: Context, projectId: string | number, id: string): Promise<boolean> {
    try {
        await context.api.request<unknown>({
            method: 'GET',
            path: `${projectPath(projectId)}/external_data_sources/${encodeURIComponent(id)}/?compact=true&include_schemas=false`,
        })
        return true
    } catch {
        return false
    }
}

async function schemasOfSource(context: Context, projectId: string | number, sourceId: string): Promise<SchemaRef[]> {
    const source = await context.api.request<{
        schemas?: { id: string; name: string; should_sync?: boolean; latest_error?: string | null }[]
    }>({
        method: 'GET',
        path: `${projectPath(projectId)}/external_data_sources/${encodeURIComponent(sourceId)}/?compact=true`,
    })
    const schemas = (source.schemas ?? []).filter((schema) => schema.latest_error || schema.should_sync)
    schemas.sort((a, b) => Number(Boolean(b.latest_error)) - Number(Boolean(a.latest_error)))
    return schemas.map((schema) => ({ id: schema.id, name: schema.name }))
}

const tool = (): ToolBase<typeof schema, SyncLogsResult> => ({
    name: 'external-data-sync-logs',
    schema,
    handler: async (context: Context, params: Params) => {
        if (!params.schema_id && !params.source_id) {
            throw new ToolInputValidationError(
                'Pass schema_id (a table id from external-data-schemas-list) or source_id (a source id from external-data-sources-list).',
                { fields: ['schema_id'] }
            )
        }
        const projectId = await context.stateManager.getProjectId()
        const limit = params.limit ?? DEFAULT_LIMIT

        const minLevel = params.level ?? 'INFO'
        const includedLevels = LEVEL_ORDER.slice(LEVEL_ORDER.indexOf(minLevel)).join(',')
        const searchParams = new URLSearchParams()
        searchParams.set('limit', String(limit))
        searchParams.set('level', includedLevels)
        if (params.job_id) {
            searchParams.set('instance_id', params.job_id)
        }
        if (params.search) {
            searchParams.set('search', params.search)
        }
        if (params.since) {
            searchParams.set('after', params.since)
        }
        if (params.until) {
            searchParams.set('before', params.until)
        }
        const fetchLogs = (schemaId: string): Promise<LogEntryPage> =>
            context.api.request<LogEntryPage>({
                method: 'GET',
                path: `${projectPath(projectId)}/external_data_schemas/${encodeURIComponent(schemaId)}/logs/?${searchParams.toString()}`,
            })

        let tables: SchemaRef[] = []
        let pages: LogEntryPage[]
        let note: string | undefined
        if (params.schema_id) {
            try {
                pages = [await fetchLogs(params.schema_id)]
            } catch (error) {
                if (
                    error instanceof PostHogApiError &&
                    error.status === 404 &&
                    (await isSourceId(context, projectId, params.schema_id))
                ) {
                    throw new ToolInputValidationError(
                        `${params.schema_id} is a data warehouse source id, not a table (schema) id. ` +
                            'Pass it as source_id to read the logs of its tables, or get table ids from ' +
                            'external-data-schemas-list (or the `schemas` of external-data-sources-retrieve) and pass one as schema_id.',
                        { fields: ['schema_id'] }
                    )
                }
                throw error
            }
        } else {
            const allTables = await schemasOfSource(context, projectId, params.source_id!)
            tables = allTables.slice(0, MAX_FANOUT_SCHEMAS)
            if (allTables.length === 0) {
                note = 'This source has no failed or syncing tables. Pass schema_id to read the logs of one table.'
            } else if (allTables.length > tables.length) {
                note =
                    `Read ${tables.length} of ${allTables.length} failed or syncing tables, failed tables first. ` +
                    'Pass schema_id to read one table.'
            }
            pages = await Promise.all(tables.map((table) => fetchLogs(table.id)))
        }

        const tagTables = !params.schema_id
        const entries: TaggedEntry[] = pages
            .flatMap((page, index) =>
                (page.results ?? []).map((entry) => (tagTables ? { ...entry, table: tables[index]!.name } : entry))
            )
            .sort((a, b) => newestFirst(a.timestamp, b.timestamp))
        const totalMatching = pages.reduce((sum, page) => sum + (page.count ?? page.results?.length ?? 0), 0)

        const result: SyncLogsResult = {
            ...(tagTables ? { tables } : {}),
            total_matching: totalMatching,
            entries_read: entries.length,
            has_more: totalMatching > entries.length,
        }
        if (params.dedupe === false) {
            result.has_more ||= entries.length > limit
            result.entries = entries.slice(0, limit).map((entry) => ({
                timestamp: entry.timestamp,
                level: entry.level,
                message: truncateText(entry.message, MESSAGE_MAX_LENGTH),
                job_id: entry.instance_id,
                ...(entry.table ? { table: entry.table } : {}),
            }))
        } else {
            const groups = dedupeLogEntries(entries)
            result.has_more ||= groups.length > limit
            result.groups = groups.slice(0, limit)
        }
        if (note) {
            result.note = note
        }
        return result
    },
})

export default tool
