import { describe, expect, it, vi } from 'vitest'

import { estimateTokens } from '@/lib/estimate-tokens'
import { formatResponse } from '@/lib/response'
import { GENERATED_TOOLS as LOGS_TOOLS } from '@/tools/generated/logs'
import { GENERATED_TOOLS as PRODUCT_ANALYTICS_TOOLS } from '@/tools/generated/product_analytics'
import { GENERATED_TOOLS as SIGNALS_TOOLS } from '@/tools/generated/signals'
import type { Context } from '@/tools/types'

/**
 * Each budget is the size that keeps one default page usable inside an agent's context, measured on
 * an ordinary page of invented data, not the size the payload happens to be today.
 */
const LOGS_TOKEN_BUDGET = 20_000
const INSIGHTS_TOKEN_BUDGET = 18_000
const INBOX_TOKEN_BUDGET = 10_000

const LOG_ROW_COUNT = 100
const POD_COUNT = 3
const INSIGHT_COUNT = 100
const REPORT_COUNT = 20

/** The `UserBasic` keys an agent cannot act on. Name and email stay. */
const STRIPPED_USER_FIELDS = ['uuid', 'distinct_id', 'is_email_verified', 'hedgehog_config']

function createMockContext(result: unknown): Context {
    return {
        api: {
            request: vi.fn().mockResolvedValue(result),
            getProjectBaseUrl: () => 'https://us.posthog.com/project/7',
        },
        stateManager: { getProjectId: async () => 7 },
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    } as unknown as Context
}

function createUser(id: number, firstName: string, lastName: string): Record<string, unknown> {
    return {
        id,
        uuid: `00000000-0000-4000-8000-0000000000${id}`,
        distinct_id: `distinct-id-for-user-${id}`,
        first_name: firstName,
        last_name: lastName,
        email: `${firstName.toLowerCase()}@example.com`,
        is_email_verified: true,
        hedgehog_config: {
            use_as_profile: false,
            color: 'invert-hue',
            accessories: ['flag', 'sunglasses', 'parrot'],
            skin: 'default',
        },
        role_at_organization: 'engineering',
    }
}

function createResourceAttributes(pod: number): Record<string, string> {
    return {
        'service.name': 'widget-api',
        'service.version': '2026.10.3-4f1c2a9',
        'service.namespace': 'widgets',
        'deployment.environment': 'production',
        'k8s.namespace.name': 'widgets',
        'k8s.deployment.name': 'widget-api',
        'k8s.replicaset.name': 'widget-api-6d8f9b7c5d',
        'k8s.pod.name': `widget-api-6d8f9b7c5d-x${pod}k2p`,
        'k8s.pod.uid': `9a1f3c2e-0000-4000-8000-00000000000${pod}`,
        'k8s.pod.ip': `10.0.12.${10 + pod}`,
        'k8s.node.name': `ip-10-0-1-${100 + pod}.compute.internal`,
        'k8s.container.name': 'widget-api',
        'container.id': `${pod}`.repeat(64),
        'host.name': `widget-api-6d8f9b7c5d-x${pod}k2p`,
        'host.arch': 'amd64',
        'cloud.provider': 'aws',
        'cloud.region': 'us-east-1',
        'cloud.availability_zone': 'us-east-1b',
        'process.runtime.name': 'node',
        'process.runtime.version': '22.11.0',
        'process.pid': '1',
        'telemetry.sdk.name': 'opentelemetry',
        'telemetry.sdk.language': 'nodejs',
        'telemetry.sdk.version': '1.30.1',
    }
}

function createLogBody(index: number): string {
    if (index % 20 === 0) {
        return [
            `Error: widget ${index} could not be rendered`,
            '    at renderWidget (/app/dist/widgets/render.js:118:15)',
            '    at async WidgetController.show (/app/dist/widgets/controller.js:42:9)',
            '    at async Router.handle (/app/node_modules/router/lib/router.js:284:7)',
            '    at async Server.onRequest (/app/dist/server.js:77:5)',
        ].join('\n')
    }
    if (index % 5 === 0) {
        return JSON.stringify({
            msg: 'widget cache refreshed',
            widget_id: `wdg_${index}`,
            entries: 120 + index,
            duration_ms: 35 + (index % 17),
        })
    }
    return `GET /api/widgets/${index} 200 in ${20 + (index % 40)}ms`
}

function createLogRow(index: number): Record<string, unknown> {
    const pod = index % POD_COUNT
    const timestamp = new Date(Date.UTC(2026, 9, 1, 12, 0, 0) - index * 1500).toISOString()
    const isError = index % 20 === 0
    return {
        uuid: `01920000-0000-7000-8000-${String(index).padStart(12, '0')}`,
        timestamp,
        observed_timestamp: timestamp,
        body: createLogBody(index),
        severity_text: isError ? 'error' : 'info',
        severity_number: isError ? 17 : 9,
        level: isError ? 'error' : 'info',
        trace_id: index % 2 === 0 ? `4bf92f3577b34da6a3ce929d0e0e${String(index).padStart(4, '0')}` : '0'.repeat(32),
        span_id: index % 2 === 0 ? `00f067aa0ba9${String(index).padStart(4, '0')}` : '0'.repeat(16),
        attributes: {
            'http.method': 'GET',
            'http.route': '/api/widgets/:id',
            'http.status_code': isError ? '500' : '200',
            'http.user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
            request_id: `req_${String(index).padStart(8, '0')}`,
            'code.filepath': '/app/dist/widgets/controller.js',
        },
        resource_attributes: createResourceAttributes(pod),
        event_name: '',
        instrumentation_scope: 'widget-api',
        resource_fingerprint: `1844674407370955${pod}`,
        live_logs_checkpoint: '2026-10-01T12:00:05Z',
    }
}

function createLogsQueryResponse(): Record<string, unknown> {
    return {
        query: { serviceNames: ['widget-api'], dateRange: { date_from: '-1h' }, limit: LOG_ROW_COUNT },
        results: Array.from({ length: LOG_ROW_COUNT }, (_, index) => createLogRow(index)),
        hasMore: true,
        nextCursor: 'eyJ0aW1lc3RhbXAiOiAiMjAyNi0xMC0wMVQxMTo1Nzo1MC41MDBaIn0=',
        maxExportableLogs: 5_000_000,
        columns: null,
    }
}

function createTrendsQuery(index: number): Record<string, unknown> {
    return {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            series: [{ kind: 'EventsNode', event: `widget step ${index}`, math: 'total' }],
            interval: 'day',
            dateRange: { date_from: '-30d' },
            breakdownFilter: { breakdown: 'widget_kind', breakdown_type: 'event', breakdown_limit: 10 },
            trendsFilter: { display: 'ActionsLineGraph', showLegend: true, aggregationAxisFormat: 'numeric' },
            filterTestAccounts: true,
        },
    }
}

/** An alert renders its insight back in full, query included, on every insight that has one. */
function createAlert(index: number): Record<string, unknown> {
    return {
        id: `0192aaaa-0000-7000-8000-${String(index).padStart(12, '0')}`,
        created_by: createUser(1, 'Ada', 'Lovelace'),
        created_at: '2026-07-01T09:00:00Z',
        insight: {
            id: 2000 + index,
            short_id: `short${index}`,
            name: `Widget metric ${index}`,
            derived_name: null,
            query: createTrendsQuery(index),
            description: `What widget metric ${index} measures`,
            dashboards: [42],
            tags: ['widgets'],
            created_by: createUser(1, 'Ada', 'Lovelace'),
            last_modified_by: createUser(2, 'Grace', 'Hopper'),
        },
        insight_short_id: `short${index}`,
        insight_display_name: `Widget metric ${index}`,
        llm_detector_available: null,
        name: `Widget metric ${index} dropped`,
        subscribed_users: [createUser(1, 'Ada', 'Lovelace'), createUser(2, 'Grace', 'Hopper')],
        threshold: { id: 'threshold-1', created_at: '2026-07-01T09:00:00Z', name: '', configuration: {} },
        condition: { type: 'absolute_value' },
        state: 'Not firing',
        enabled: true,
        last_notified_at: null,
        last_checked_at: '2026-10-01T08:00:00Z',
        schedule_start_time: null,
        next_check_at: '2026-10-02T08:00:00Z',
        checks: [],
        config: { type: 'TrendsAlertConfig', series_index: 0, check_ongoing_interval: false },
        detector_config: null,
        evaluation_delay_intervals: 0,
        calculation_interval: 'daily',
        snoozed_until: null,
        skip_weekend: false,
        schedule_restriction: null,
        last_value: 1234,
        investigation_agent_enabled: false,
        investigation_gates_notifications: false,
        investigation_inconclusive_action: 'notify',
    }
}

function createInsight(index: number): Record<string, unknown> {
    return {
        id: 2000 + index,
        short_id: `short${index}`,
        name: `Widget metric ${index}`,
        derived_name: `Widget step ${index} count`,
        query: createTrendsQuery(index),
        description: `What widget metric ${index} measures`,
        tags: ['widgets'],
        favorited: index % 7 === 0,
        dashboards: [42, 43],
        created_at: '2026-02-18T18:28:57.827410Z',
        created_by: createUser(1, 'Ada', 'Lovelace'),
        last_modified_at: '2026-06-19T07:10:12.181366Z',
        last_modified_by: createUser(2, 'Grace', 'Hopper'),
        last_viewed_at: '2026-09-30T10:00:00Z',
        alerts: index % 10 === 0 ? [createAlert(index)] : [],
        user_access_level: 'editor',
    }
}

function createInsightsPage(): Record<string, unknown> {
    return {
        count: 340,
        next: 'https://us.posthog.com/api/projects/7/insights/?limit=100&offset=100',
        previous: null,
        results: Array.from({ length: INSIGHT_COUNT }, (_, index) => createInsight(index)),
    }
}

function createReportSummary(index: number): string {
    const paragraph =
        `Widget ${index} renders fail for a share of sessions after the October release. The failures cluster on ` +
        'the settings page, where the widget loads before its configuration arrives, and the error rate climbs ' +
        'with each deploy that touches the config loader.'
    return [
        paragraph,
        '',
        '## Evidence',
        '',
        `- [Error rate](chart:chart-${index}) rose from 0.4% to 3.1% of widget renders over seven days.`,
        '- Most failing sessions come from one browser family, and none from the mobile app.',
        '- The stack trace points at `renderWidget` in `widgets/render.ts`, line 118.',
        '',
        '## Likely cause',
        '',
        `${paragraph} ${paragraph}`,
        '',
        '## Impact',
        '',
        `${paragraph} ${paragraph}`,
        '',
        '## Suggested fix',
        '',
        'Wait for the configuration before the first render, and show the empty state while it loads. ' +
            'Add a guard in `renderWidget` so a missing config logs a warning instead of throwing.',
        '',
        '## Verification plan',
        '',
        `${paragraph}`,
    ].join('\n')
}

function createReport(index: number): Record<string, unknown> {
    const summary = createReportSummary(index)
    return {
        id: `0192bbbb-0000-7000-8000-${String(index).padStart(12, '0')}`,
        title: `Widget ${index} fails to render on the settings page`,
        summary,
        summary_lead: summary.split('\n\n')[0]!.slice(0, 450),
        metrics: [
            {
                metric_id: 'error_rate',
                title: 'Widget render error rate',
                kind: 'rate',
                role: 'primary',
                value: 3.1,
                value_at: '2026-10-01T08:00:00Z',
                series: Array.from({ length: 14 }, (_, point) => (4 + point * 2) / 10),
                value_format: 'percentage',
                unit: null,
                caption: null,
            },
        ],
        status: 'ready',
        priority: 'P2',
        actionability: 'immediately_actionable',
        already_addressed: false,
        dismissal_reason: null,
        dismissal_note: null,
        suppression_source: null,
        suppression_explanation: null,
        signal_count: 12 + index,
        total_weight: 4.5,
        source_products: ['error_tracking'],
        scout_name: null,
        is_suggested_reviewer: index % 3 === 0,
        pull_requests: [],
        implementation_pr_url: null,
        implementation_pr_state: null,
        implementation_pr_merged: false,
        tracker_issue_url: null,
        tracker_issue_reference: null,
        tracker_issue_error: null,
        work_state: 'unclaimed',
        assignee: null,
        ranking: {
            status: 'scored',
            model: 'ranking-v3',
            scored_at: '2026-10-01T08:00:00Z',
            predictions: [
                { outcome: 'open', probability: 0.41, lift: 1.3 },
                { outcome: 'action', probability: 0.18, lift: 1.1 },
                { outcome: 'fix', probability: 0.07, lift: 0.9 },
            ],
        },
        created_at: '2026-09-28T10:00:00Z',
        updated_at: '2026-10-01T08:00:00Z',
    }
}

function createReportsPage(): Record<string, unknown> {
    return {
        count: 57,
        next: 'https://us.posthog.com/api/projects/7/signals/reports/?limit=20&offset=20',
        previous: null,
        results: Array.from({ length: REPORT_COUNT }, (_, index) => createReport(index)),
    }
}

describe('tool response budgets', () => {
    describe('query-logs', () => {
        const tool = LOGS_TOOLS['query-logs']!()

        async function shapeLogs(): Promise<Record<string, unknown>> {
            const params = tool.schema.parse({
                query: { serviceNames: ['widget-api'], dateRange: { date_from: '-1h' } },
            })
            return (await tool.handler(createMockContext(createLogsQueryResponse()), params)) as unknown as Record<
                string,
                unknown
            >
        }

        it(`keeps a ${LOG_ROW_COUNT}-row page within the response budget`, async () => {
            expect(estimateTokens(formatResponse(await shapeLogs()))).toBeLessThan(LOGS_TOKEN_BUDGET)
        })

        it('returns the cursor an agent needs to fetch the next page', async () => {
            const shaped = await shapeLogs()

            expect(shaped).toMatchObject({ hasMore: true, nextCursor: expect.any(String) })
        })

        it("lists each resource's attributes once, under the fingerprint every row keeps", async () => {
            const shaped = await shapeLogs()
            const rows = shaped.results as Record<string, unknown>[]
            const resources = shaped.resources as Record<string, Record<string, string>>

            expect(Object.keys(resources)).toHaveLength(POD_COUNT)
            for (const [index, row] of rows.entries()) {
                expect(row).not.toHaveProperty('resource_attributes')
                expect(resources[row.resource_fingerprint as string]).toEqual(
                    createResourceAttributes(index % POD_COUNT)
                )
            }
        })
    })

    describe('insights-list', () => {
        const tool = PRODUCT_ANALYTICS_TOOLS['insights-list']!()

        async function shapeInsights(): Promise<{ results: Record<string, any>[] }> {
            return (await tool.handler(createMockContext(createInsightsPage()), tool.schema.parse({}))) as unknown as {
                results: Record<string, any>[]
            }
        }

        it(`keeps a ${INSIGHT_COUNT}-insight page within the response budget`, async () => {
            expect(estimateTokens(formatResponse(await shapeInsights()))).toBeLessThan(INSIGHTS_TOKEN_BUDGET)
        })

        it('keeps the owner and alert fields an agent acts on, without their nested copies', async () => {
            const insight = (await shapeInsights()).results[0]!

            expect(insight.created_by).toEqual({
                id: 1,
                first_name: 'Ada',
                last_name: 'Lovelace',
                email: 'ada@example.com',
            })
            expect(insight.last_modified_by.email).toBe('grace@example.com')
            for (const field of STRIPPED_USER_FIELDS) {
                expect(insight.last_modified_by).not.toHaveProperty(field)
            }
            expect(insight.alerts).toEqual([
                { id: createAlert(0).id, name: 'Widget metric 0 dropped', state: 'Not firing', enabled: true },
            ])
        })
    })

    describe('inbox-reports-list', () => {
        const tool = SIGNALS_TOOLS['inbox-reports-list']!()

        async function shapeReports(): Promise<{ results: Record<string, unknown>[] }> {
            return (await tool.handler(
                createMockContext(createReportsPage()),
                tool.schema.parse({ limit: REPORT_COUNT })
            )) as unknown as { results: Record<string, unknown>[] }
        }

        it(`keeps a ${REPORT_COUNT}-report page within the response budget`, async () => {
            expect(estimateTokens(formatResponse(await shapeReports()))).toBeLessThan(INBOX_TOKEN_BUDGET)
        })

        it('carries the summary lead in place of the full summary', async () => {
            const report = (await shapeReports()).results[0]!

            expect(report.summary_lead).toContain('Widget 0 renders fail')
            expect(report).not.toHaveProperty('summary')
        })
    })
})
