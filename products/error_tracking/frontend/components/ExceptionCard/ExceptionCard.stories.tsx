import { Meta } from '@storybook/react'
import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { ErrorEventType } from 'lib/components/Errors/types'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema/schema-general'

import { TEST_EVENTS } from '../../__mocks__/events'
import { StyleVariables } from '../StyleVariables'
import { ExceptionCard } from './ExceptionCard'
import { exceptionCardLogic } from './exceptionCardLogic'

const meta: Meta = {
    title: 'ErrorTracking/ExceptionCard',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            post: {
                'api/environments/:team_id/error_tracking/stack_frames/batch_get/': require('../../__mocks__/stack_frames/batch_get'),
            },
        }),
        (Story) => (
            <StyleVariables>
                {/* 👇 Decorators in Storybook also accept a function. Replace <Story/> with Story() to enable it  */}
                <Story />
            </StyleVariables>
        ),
    ],
}

export default meta

function asErrorEventType(event: unknown): ErrorEventType {
    return event as unknown as ErrorEventType
}

////////////////////// Generic stacktraces

export function ExceptionCardBase(): JSX.Element {
    return (
        <div className="w-[1000px] h-[700px]">
            <BindLogic logic={exceptionCardLogic} props={{ issueId: 'issue-id' }}>
                <OpenSessionTab>
                    <ExceptionCard
                        issueId="issue-id"
                        issueName="Test Issue"
                        loading={false}
                        event={TEST_EVENTS['javascript_resolved'] as any}
                    />
                </OpenSessionTab>
            </BindLogic>
        </div>
    )
}
ExceptionCardBase.parameters = sessionTimelineParameters(asErrorEventType(TEST_EVENTS['javascript_resolved']))

export function ExceptionCardNoInApp(): JSX.Element {
    return (
        <div className="w-[800px]">
            <ExceptionCard
                issueId="issue-id"
                issueName="Test Issue"
                loading={false}
                event={TEST_EVENTS['javascript_no_in_app'] as any}
            />
        </div>
    )
}
ExceptionCardNoInApp.parameters = sessionTimelineParameters(asErrorEventType(TEST_EVENTS['javascript_no_in_app']))

export function ExceptionCardLoading(): JSX.Element {
    return (
        <div className="w-[800px]">
            <ExceptionCard issueId="issue-id" issueName={null} loading={true} event={undefined} />
        </div>
    )
}
ExceptionCardLoading.tags = ['test-skip']

export function ExceptionCardSessionTimelineWithSteps(): JSX.Element {
    const event = buildSessionTimelineEvent([
        {
            type: 'ui.interaction',
            message: 'Button clicked',
            level: 'info',
            timestamp: '2024-07-09T12:00:02.500Z',
        },
        {
            type: 'http',
            message: 'API request started',
            level: 'info',
            timestamp: '2024-07-09T12:00:03.800Z',
        },
        {
            type: 'state',
            message: 'State updated',
            level: 'debug',
            timestamp: '2024-07-09T12:00:03.800Z',
        },
    ])

    return <ExceptionCardSessionTimelineStory event={event} />
}
ExceptionCardSessionTimelineWithSteps.parameters = sessionTimelineParameters(
    buildSessionTimelineEvent([
        {
            type: 'ui.interaction',
            message: 'Button clicked',
            level: 'info',
            timestamp: '2024-07-09T12:00:02.500Z',
        },
        {
            type: 'http',
            message: 'API request started',
            level: 'info',
            timestamp: '2024-07-09T12:00:03.800Z',
        },
        {
            type: 'state',
            message: 'State updated',
            level: 'debug',
            timestamp: '2024-07-09T12:00:03.800Z',
        },
    ])
)

export function ExceptionCardSessionTimelineWithoutSteps(): JSX.Element {
    const event = buildSessionTimelineEvent()
    return <ExceptionCardSessionTimelineStory event={event} />
}
ExceptionCardSessionTimelineWithoutSteps.parameters = sessionTimelineParameters(buildSessionTimelineEvent())

export function ExceptionCardSessionTimelineWithMalformedSteps(): JSX.Element {
    const event = buildSessionTimelineEvent([
        {
            type: 'ui.interaction',
            message: 'Button clicked',
            level: 'info',
            timestamp: '2024-07-09T12:00:02.500Z',
        },
        {
            bad: 'row',
        },
    ])

    return <ExceptionCardSessionTimelineStory event={event} />
}
ExceptionCardSessionTimelineWithMalformedSteps.parameters = sessionTimelineParameters(
    buildSessionTimelineEvent([
        {
            type: 'ui.interaction',
            message: 'Button clicked',
            level: 'info',
            timestamp: '2024-07-09T12:00:02.500Z',
        },
        {
            bad: 'row',
        },
    ])
)

export function ExceptionCardSessionTimelineWithLongPreviewTexts(): JSX.Element {
    const event = buildLongPreviewTextEvent()
    return <ExceptionCardSessionTimelineStory event={event} containerClassName="w-[560px] h-[700px]" />
}
ExceptionCardSessionTimelineWithLongPreviewTexts.parameters = sessionTimelineParameters(buildLongPreviewTextEvent())

////////////////////// No session ID

const NO_SESSION_STEPS = [
    {
        type: 'ui.interaction',
        message: 'Button clicked',
        level: 'info',
        timestamp: '2024-07-09T12:00:02.500Z',
    },
    {
        type: 'http',
        message: 'API request started',
        level: 'info',
        timestamp: '2024-07-09T12:00:03.800Z',
    },
    {
        type: 'state',
        message: 'State updated',
        level: 'debug',
        timestamp: '2024-07-09T12:00:04.200Z',
    },
]

export function ExceptionCardNoSessionWithSteps(): JSX.Element {
    const event = buildSessionTimelineEvent(NO_SESSION_STEPS, { sessionId: null })
    return <ExceptionCardSessionTimelineStory event={event} />
}

export function ExceptionCardNoSessionWithoutSteps(): JSX.Element {
    const event = buildSessionTimelineEvent(undefined, { sessionId: null })
    return <ExceptionCardSessionTimelineStory event={event} />
}

//////////////////// Utils

function ExceptionCardSessionTimelineStory({
    event,
    containerClassName = 'w-[1000px] h-[700px]',
}: {
    event: ErrorEventType
    containerClassName?: string
}): JSX.Element {
    return (
        <div className={containerClassName}>
            <BindLogic logic={exceptionCardLogic} props={{ issueId: 'issue-id' }}>
                <OpenSessionTab>
                    <ExceptionCard issueId="issue-id" issueName="Test Issue" loading={false} event={event} />
                </OpenSessionTab>
            </BindLogic>
        </div>
    )
}

function buildLongPreviewTextEvent(): ErrorEventType {
    const event = buildSessionTimelineEvent([
        {
            type: `ui.interaction.${'t'.repeat(180)}`,
            message: `Step before crash: ${'m'.repeat(220)}`,
            level: 'info',
            timestamp: '2024-07-09T12:00:02.500Z',
        },
        {
            type: 'http',
            message: 'API request started',
            level: 'info',
            timestamp: '2024-07-09T12:00:03.800Z',
        },
    ])

    return {
        ...event,
        properties: {
            ...event.properties,
            $exception_list: [
                {
                    type: `VeryLongExceptionType${'X'.repeat(170)}`,
                    value: `Extremely long exception message intended for truncation coverage ${'Y'.repeat(220)}`,
                },
            ],
        },
    }
}

type StoryCombinedEventRow = [
    uuid: string,
    eventName: string,
    timestamp: string,
    lib: string | null,
    currentUrl: string | null,
    exceptionList: Array<{ type?: string; value?: string }> | null,
    exceptionFingerprint: string | null,
    exceptionIssueId: string | null,
]

type StoryEventDetailsRow = [uuid: string, eventName: string, timestamp: string, properties: Record<string, unknown>]
type StoryExceptionRow = [uuid: string, timestamp: string, properties: string]
type StoryPageRow = [uuid: string, timestamp: string, url: string, lib: string]
type StoryCustomRow = [uuid: string, eventName: string, timestamp: string, lib: string]
type StoryLogRow = [timestamp: string, level: string, message: string]

interface TimelineQueryLike {
    after?: string
    before?: string
    orderBy?: string[]
    limit?: number
    select?: string[]
    where?: unknown[]
    kind?: NodeKind
    query?: string
}

function toTimestampMs(value: unknown): number {
    if (value instanceof Date || typeof value === 'string' || typeof value === 'number') {
        return new Date(value).getTime()
    }

    return Number.NaN
}

function sessionTimelineParameters(event: ErrorEventType): Record<string, unknown> {
    const center = new Date(event.timestamp).getTime()
    const at = (deltaMs: number): string => new Date(center + deltaMs).toISOString()

    const exceptionList = Array.isArray(event.properties?.$exception_list) ? event.properties.$exception_list : []
    const exceptionRows: StoryExceptionRow[] = [[event.uuid, event.timestamp, JSON.stringify(event.properties)]]
    const pageRows: StoryPageRow[] = [
        ['page-1', at(-15000), 'https://app.example.com/home', 'web'],
        ['page-2', at(-7000), 'https://app.example.com/demo', 'web'],
    ]
    const customRows: StoryCustomRow[] = [
        ['custom-1', 'form_opened', at(-11000), 'web'],
        ['custom-2', 'button_clicked', at(-3000), 'web'],
    ]
    const combinedEventRows: StoryCombinedEventRow[] = [
        ['page-1', '$pageview', at(-15000), 'web', 'https://app.example.com/home', null, null, null],
        ['custom-1', 'form_opened', at(-11000), 'web', null, null, null, null],
        ['page-2', '$pageview', at(-7000), 'web', 'https://app.example.com/demo', null, null, null],
        [
            'previous-exception',
            '$exception',
            at(-4500),
            'web',
            null,
            [{ type: 'ReferenceError', value: 'window.appConfig is undefined' }],
            'prev-fingerprint',
            'issue-id',
        ],
        ['custom-2', 'button_clicked', at(-3000), 'web', null, null, null, null],
        [
            event.uuid,
            '$exception',
            event.timestamp,
            event.properties?.$lib ?? 'web',
            null,
            exceptionList,
            event.properties?.$exception_fingerprint ?? 'current-fingerprint',
            event.properties?.$exception_issue_id ?? 'issue-id',
        ],
    ]

    const eventDetailsRowsEntries: Array<[string, StoryEventDetailsRow]> = combinedEventRows.map(
        (row): [string, StoryEventDetailsRow] => {
            const [uuid, eventName, ts, lib, currentUrl, exceptionListForRow, exceptionFingerprint, exceptionIssueId] =
                row
            const baseProperties = {
                ...(lib ? { $lib: lib } : {}),
                ...(currentUrl ? { $current_url: currentUrl } : {}),
                ...(exceptionListForRow ? { $exception_list: exceptionListForRow } : {}),
                ...(exceptionFingerprint ? { $exception_fingerprint: exceptionFingerprint } : {}),
                ...(exceptionIssueId ? { $exception_issue_id: exceptionIssueId } : {}),
            }

            const properties = uuid === event.uuid ? event.properties : baseProperties
            return [String(uuid), [uuid, eventName, ts, properties]]
        }
    )

    const eventDetailsRowsByUuid = Object.fromEntries(eventDetailsRowsEntries) as Record<string, StoryEventDetailsRow>

    const logRows: StoryLogRow[] = [
        [at(-13000), 'info', 'App initialized'],
        [at(-6000), 'warn', 'Slow network detected'],
        [at(-3500), 'info', 'Form submitted'],
        [at(-1200), 'error', 'Console error before exception'],
    ]

    const filterRows = <T extends unknown[]>(rows: T[], timestampIndex: number, query: TimelineQueryLike): T[] => {
        const after = query.after ? new Date(query.after).getTime() : Number.NEGATIVE_INFINITY
        const before = query.before ? new Date(query.before).getTime() : Number.POSITIVE_INFINITY
        const descending = query.orderBy?.some((clause: string) => clause.includes('DESC'))
        const limit = typeof query.limit === 'number' ? query.limit : rows.length

        const filtered = rows.filter((row) => {
            const timestamp = toTimestampMs(row[timestampIndex])
            return Number.isFinite(timestamp) && timestamp >= after && timestamp <= before
        })

        return filtered
            .sort((a, b) => {
                const aTimestamp = toTimestampMs(a[timestampIndex])
                const bTimestamp = toTimestampMs(b[timestampIndex])
                const diff =
                    (Number.isFinite(aTimestamp) ? aTimestamp : 0) - (Number.isFinite(bTimestamp) ? bTimestamp : 0)
                return descending ? -diff : diff
            })
            .slice(0, limit)
    }

    const filterLogRowsFromHogQL = <T extends [string, ...unknown[]]>(rows: T[], query: TimelineQueryLike): T[] => {
        const queryString = String(query?.query ?? '')
        const descending = /ORDER BY\s+timestamp\s+DESC/i.test(queryString)
        const limitMatch = queryString.match(/LIMIT\s+(\d+)/i)
        const limit = limitMatch ? parseInt(limitMatch[1], 10) : rows.length

        const isoMatches = Array.from(queryString.matchAll(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z/g), (m) =>
            new Date(m[0]).getTime()
        )

        const lowerBound = isoMatches[0] ?? Number.NEGATIVE_INFINITY
        const upperBound = isoMatches[1] ?? Number.POSITIVE_INFINITY

        const filtered = rows.filter((row) => {
            const ts = new Date(row[0]).getTime()
            if (descending) {
                return ts >= lowerBound && ts < upperBound
            }
            return ts > lowerBound && ts <= upperBound
        })

        return filtered
            .sort((a, b) => {
                const diff = new Date(a[0]).getTime() - new Date(b[0]).getTime()
                return descending ? -diff : diff
            })
            .slice(0, limit)
    }

    const queryHandler = async (req: any, res: any, ctx: any): Promise<unknown> => {
        const body = await req.clone().json()
        const query = body.query as TimelineQueryLike

        if (query.kind === NodeKind.EventsQuery) {
            const isCombinedEventLoaderQuery =
                query.select?.includes('event') &&
                query.select?.includes('properties.$current_url') &&
                query.select?.includes('properties.$exception_list')

            if (isCombinedEventLoaderQuery) {
                return res(ctx.json({ results: filterRows(combinedEventRows, 2, query) }))
            }

            const isEventDetailsQuery =
                query.select?.includes('uuid') &&
                query.select?.includes('event') &&
                query.select?.includes('properties')

            if (isEventDetailsQuery) {
                const uuidClause = query.where?.find(
                    (clause: unknown) => typeof clause === 'string' && String(clause).startsWith('equals(uuid,')
                )
                const uuidMatch =
                    typeof uuidClause === 'string' ? uuidClause.match(/equals\(uuid,\s*'([^']+)'\)/) : null
                const eventRow = uuidMatch ? eventDetailsRowsByUuid[uuidMatch[1]] : null
                return res(ctx.json({ results: eventRow ? [eventRow] : [] }))
            }

            if (query.select?.includes('properties.$current_url')) {
                return res(ctx.json({ results: filterRows(pageRows, 1, query) }))
            }

            if (query.select?.includes('event')) {
                return res(ctx.json({ results: filterRows(customRows, 2, query) }))
            }

            if (query.select?.includes('properties')) {
                return res(ctx.json({ results: filterRows(exceptionRows, 1, query) }))
            }

            return res(ctx.json({ results: filterRows(combinedEventRows, 2, query) }))
        }

        if (query.kind === NodeKind.HogQLQuery) {
            return res(ctx.json({ results: filterLogRowsFromHogQL(logRows, query) }))
        }

        return res(ctx.json({ results: [] }))
    }

    return {
        msw: {
            mocks: {
                post: {
                    'api/environments/:team_id/query': queryHandler,
                    '/api/environments/:team_id/query': queryHandler,
                    '/api/environments/:team_id/query/': queryHandler,
                    '/api/environments/:team_id/query/:query_kind': queryHandler,
                    '/api/environments/:team_id/query/:query_kind/': queryHandler,
                },
            },
        },
    }
}

function normalizeExceptionStepForStory(step: unknown): unknown {
    if (!step || typeof step !== 'object' || Array.isArray(step)) {
        return step
    }

    const record = step as Record<string, unknown>
    const { type, message, level, timestamp, ...rest } = record

    return {
        ...rest,
        ...(record.$type !== undefined ? { $type: record.$type } : typeof type === 'string' ? { $type: type } : {}),
        ...(record.$message !== undefined
            ? { $message: record.$message }
            : typeof message === 'string'
              ? { $message: message }
              : {}),
        ...(record.$level !== undefined
            ? { $level: record.$level }
            : typeof level === 'string'
              ? { $level: level }
              : {}),
        ...(record.$timestamp !== undefined
            ? { $timestamp: record.$timestamp }
            : typeof timestamp === 'string' || typeof timestamp === 'number'
              ? { $timestamp: timestamp }
              : {}),
    }
}

function buildSessionTimelineEvent(
    exceptionSteps?: any[],
    { sessionId = 'session-with-steps' }: { sessionId?: string | null } = {}
): ErrorEventType {
    const baseEvent = asErrorEventType(TEST_EVENTS['javascript_resolved'])
    const { $session_id: _dropped, ...baseWithoutSession } = baseEvent.properties as Record<string, unknown>

    const baseProperties = {
        ...baseWithoutSession,
        ...(sessionId != null ? { $session_id: sessionId } : {}),
        $lib: 'web',
    }

    const normalizedExceptionSteps = exceptionSteps?.map(normalizeExceptionStepForStory)

    return {
        ...baseEvent,
        uuid: 'current-exception-uuid',
        timestamp: '2024-07-09T12:00:05.000Z',
        properties:
            normalizedExceptionSteps !== undefined
                ? { ...baseProperties, $exception_steps: normalizedExceptionSteps }
                : baseProperties,
    }
}

function OpenSessionTab({ children }: { children: JSX.Element }): JSX.Element {
    const { setCurrentTab } = useActions(exceptionCardLogic({ issueId: 'issue-id' }))

    useEffect(() => {
        setCurrentTab('session')
    }, [setCurrentTab])

    return children
}

//////////////////// All Events

function ExceptionCardWrapperAllEvents({
    children,
}: {
    children: (issueId: string, event: Partial<ErrorEventType>) => JSX.Element
}): JSX.Element {
    return (
        <div className="space-y-8">
            {Object.entries(TEST_EVENTS).map(([name, evt]: [string, any]) => {
                return <div key={name}>{children(name, evt)}</div>
            })}
        </div>
    )
}

export function ExceptionCardAllEvents(): JSX.Element {
    return (
        <ExceptionCardWrapperAllEvents>
            {(issueId, event) => (
                <ExceptionCard issueId={issueId} issueName={null} loading={false} event={event as ErrorEventType} />
            )}
        </ExceptionCardWrapperAllEvents>
    )
}
