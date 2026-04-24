import { z } from 'zod'

import { pickResponseFields } from '@/tools/tool-utils'
import { POSTHOG_META_KEY, type Context, type ToolBase } from '@/tools/types'

import { normalizeErrorTrackingProperty } from './exceptionProperties'

const dateRangeSchema = z
    .object({
        date_from: z.string().optional(),
        date_to: z.string().nullable().optional(),
    })
    .optional()

const schema = z.object({
    issueId: z
        .string()
        .regex(/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/)
        .describe('Error tracking issue ID.'),
    dateRange: dateRangeSchema.default({ date_from: '-7d' }).optional(),
    filterTestAccounts: z.coerce
        .boolean()
        .default(true)
        .optional()
        .describe('When true, exclude internal/test account data from results. Defaults to true.'),
    volumeResolution: z.coerce.number().int().min(0).default(0).optional(),
    includeSparkline: z.coerce
        .boolean()
        .default(false)
        .optional()
        .describe('Set true to include a compact numeric occurrence sparkline. Defaults to false to save tokens.'),
})

type Params = z.infer<typeof schema>

const ISSUE_FIELDS = [
    'id',
    'name',
    'description',
    'status',
    'first_seen',
    'last_seen',
    'library',
    'source',
    'function',
    'assignee',
    'aggregations',
]

const CONTEXT_EVENT_SELECTS = ['properties.$exception_list', 'properties.$exception_releases']

function escapeHogQLString(value: string): string {
    return value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")
}

function normalizeColumn(column: unknown): string {
    if (typeof column === 'string') {
        return column
    }
    if (column && typeof column === 'object') {
        const record = column as Record<string, unknown>
        for (const key of ['key', 'name', 'id', 'field']) {
            if (typeof record[key] === 'string') {
                return record[key] as string
            }
        }
    }
    return ''
}

function compactObject(record: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries(
        Object.entries(record).filter(([, value]) => {
            if (value === undefined || value === null) {
                return false
            }
            if (Array.isArray(value)) {
                return value.length > 0
            }
            if (typeof value === 'object') {
                return Object.keys(value as Record<string, unknown>).length > 0
            }
            return true
        })
    )
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined
}

function toNumber(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function mapContextEventProperties(data: Record<string, unknown>): Record<string, unknown> {
    const row = Array.isArray(data.results) ? data.results[0] : undefined
    if (!row) {
        return {}
    }

    const columns = Array.isArray(data.columns) ? data.columns.map(normalizeColumn) : CONTEXT_EVENT_SELECTS
    const values = Array.isArray(row) ? row : columns.map((column) => (row as Record<string, unknown>)?.[column])
    const properties: Record<string, unknown> = {}

    for (let i = 0; i < columns.length; i++) {
        const column = columns[i] ?? ''
        if (!column.startsWith('properties.')) {
            continue
        }
        const value = values[i]
        if (value !== undefined && value !== null) {
            const prop = column.slice('properties.'.length)
            properties[prop] = normalizeErrorTrackingProperty(prop, value, { verbosity: 'stack', onlyAppFrames: true })
        }
    }

    return properties
}

function getFrameValue(frame: Record<string, unknown>, keys: string[]): unknown {
    for (const key of keys) {
        const value = frame[key]
        if (value !== undefined && value !== null && value !== '') {
            return value
        }
    }
    return undefined
}

function getFrames(exceptionList: unknown): Record<string, unknown>[] {
    if (!Array.isArray(exceptionList)) {
        return []
    }

    const frames: Record<string, unknown>[] = []
    for (const exception of exceptionList) {
        const exceptionRecord = asRecord(exception)
        const stacktrace = asRecord(exceptionRecord?.stacktrace)
        const exceptionFrames = stacktrace?.frames
        if (Array.isArray(exceptionFrames)) {
            frames.push(...exceptionFrames.filter((frame): frame is Record<string, unknown> => !!asRecord(frame)))
        }
    }
    return frames
}

function buildTopInAppFrame(
    issue: Record<string, unknown>,
    eventProperties: Record<string, unknown>
): Record<string, unknown> {
    const frames = getFrames(eventProperties.$exception_list)
    const topFrame = [...frames].reverse().find((frame) => frame.in_app === true)

    if (!topFrame) {
        return {}
    }

    const frameFunction = getFrameValue(topFrame, ['function', 'mangled_name', 'name'])
    const fallbackFunction = typeof issue.function === 'string' ? issue.function : undefined
    const fn = typeof frameFunction === 'string' && frameFunction !== '?' ? frameFunction : fallbackFunction

    const frameSource = getFrameValue(topFrame, ['source', 'filename', 'abs_path', 'module'])
    const fallbackSource = typeof issue.source === 'string' ? issue.source : undefined

    return compactObject({
        function: fn,
        source: frameSource ?? fallbackSource,
        line: getFrameValue(topFrame, ['line', 'lineno']),
        column: getFrameValue(topFrame, ['column', 'colno']),
        in_app: true,
    })
}

function extractLatestRelease(eventProperties: Record<string, unknown>): Record<string, unknown> {
    const releases = eventProperties.$exception_releases
    const releaseValues = Array.isArray(releases)
        ? releases
        : releases && typeof releases === 'object'
          ? Object.values(releases)
          : []
    const release = releaseValues
        .filter((value): value is Record<string, unknown> => !!asRecord(value))
        .sort(
            (a, b) =>
                Date.parse(String(b.timestamp ?? b.created_at ?? 0)) -
                Date.parse(String(a.timestamp ?? a.created_at ?? 0))
        )[0]

    if (!release) {
        return {}
    }

    const metadata = asRecord(release.metadata)
    const git = asRecord(metadata?.git)
    return compactObject({
        version: release.version,
        project: release.project,
        timestamp: release.timestamp ?? release.created_at,
        commit_id: git?.commit_id,
        branch: git?.branch,
        repo_name: git?.repo_name,
    })
}

function buildImpact(issue: Record<string, unknown>): Record<string, unknown> {
    const aggregations = asRecord(issue.aggregations)
    return compactObject({
        occurrences: toNumber(aggregations?.occurrences),
        users: toNumber(aggregations?.users),
        sessions: toNumber(aggregations?.sessions),
    })
}

function buildSparkline(issue: Record<string, unknown>): number[] | undefined {
    const aggregations = asRecord(issue.aggregations)
    const volumeRange = aggregations?.volumeRange
    if (Array.isArray(volumeRange) && volumeRange.every((value) => typeof value === 'number')) {
        return volumeRange
    }

    const volumeBuckets = aggregations?.volume_buckets
    if (Array.isArray(volumeBuckets)) {
        const values = volumeBuckets
            .map((bucket) => asRecord(bucket)?.value)
            .filter((value): value is number => typeof value === 'number')
        return values.length > 0 ? values : undefined
    }

    return undefined
}

export const queryIssueHandler: ToolBase<typeof schema>['handler'] = async (context: Context, rawParams: Params) => {
    const params = schema.parse(rawParams)
    const projectId = await context.stateManager.getProjectId()
    const baseUrl = context.api.getProjectBaseUrl(projectId)
    const posthogUrl = `${baseUrl}/error_tracking/${encodeURIComponent(params.issueId)}`
    const volumeResolution = params.includeSparkline
        ? params.volumeResolution && params.volumeResolution > 0
            ? params.volumeResolution
            : 12
        : params.volumeResolution

    const query = {
        kind: 'ErrorTrackingQuery',
        issueId: params.issueId,
        dateRange: params.dateRange,
        filterTestAccounts: params.filterTestAccounts,
        volumeResolution,
        limit: 1,
        orderBy: 'last_seen',
        orderDirection: 'DESC',
        withAggregations: true,
        withFirstEvent: false,
        withLastEvent: false,
        tags: { productKey: 'error_tracking' },
    }

    const data = await context.api.query({ projectId }).runQuery({ query })
    const issue = Array.isArray(data.results) ? data.results[0] : undefined

    if (!issue || typeof issue !== 'object') {
        return { result: null, _posthogUrl: posthogUrl }
    }
    const issueRecord = issue as Record<string, unknown>
    const escapedIssueId = escapeHogQLString(params.issueId)
    const contextEventQuery = {
        kind: 'EventsQuery',
        event: '$exception',
        select: CONTEXT_EVENT_SELECTS,
        where: [`(issue_id = '${escapedIssueId}' OR properties.$exception_issue_id = '${escapedIssueId}')`],
        filterTestAccounts: params.filterTestAccounts,
        after: params.dateRange?.date_from,
        before: params.dateRange?.date_to ?? undefined,
        orderBy: ['timestamp DESC'],
        limit: 1,
        tags: { productKey: 'error_tracking' },
    }
    const eventData = await context.api.query({ projectId }).runQuery({ query: contextEventQuery })
    const eventProperties = mapContextEventProperties(eventData as Record<string, unknown>)

    return compactObject({
        ...pickResponseFields(issueRecord, ISSUE_FIELDS),
        top_in_app_frame: buildTopInAppFrame(issueRecord, eventProperties),
        latest_release: extractLatestRelease(eventProperties),
        impact: buildImpact(issueRecord),
        sparkline: params.includeSparkline ? buildSparkline(issueRecord) : undefined,
        _posthogUrl: posthogUrl,
    })
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'query-error-tracking-issue',
    schema,
    handler: queryIssueHandler,
    _meta: {
        [POSTHOG_META_KEY]: { outputFormat: 'json' },
    },
})

export default tool
