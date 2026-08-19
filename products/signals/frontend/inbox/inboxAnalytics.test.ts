import posthog from 'posthog-js'

import {
    captureInboxQueryChanged,
    captureInboxReportAction,
    captureInboxReportClosed,
    captureInboxReportScrolled,
    captureInboxReportsImpressed,
    captureInboxSettingsChanged,
    captureInboxViewed,
    captureScoutConfigChanged,
    captureSignalSourceConnected,
    INBOX_EVENTS,
} from './inboxAnalytics'
import { SignalReport, SignalReportStatus } from './types'

jest.mock('posthog-js')

function lastCapture(event: string): Record<string, any> | undefined {
    const calls = (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name === event)
    return calls.length > 0 ? calls[calls.length - 1][1] : undefined
}

function makeReport(overrides: Partial<SignalReport> = {}): SignalReport {
    return {
        id: 'r1',
        title: 'Something broke',
        summary: null,
        status: SignalReportStatus.READY,
        total_weight: 1,
        signal_count: 1,
        relevant_user_count: null,
        created_at: '2026-06-20T00:00:00Z',
        updated_at: '2026-06-20T00:00:00Z',
        artefact_count: 0,
        is_suggested_reviewer: false,
        priority: 'P1',
        actionability: 'immediately_actionable',
        ...overrides,
    }
}

describe('inboxAnalytics', () => {
    beforeEach(() => {
        ;(posthog.capture as jest.Mock).mockClear()
    })

    it('stamps every event with the cloud client discriminator', () => {
        captureInboxViewed({
            tab: 'reports',
            reports: [],
            totalCount: 0,
            pullsTabCount: 3,
            reportsTabCount: 212,
            hasActiveFilters: false,
            sourceProductFilter: [],
            priorityFilter: [],
            scope: 'for-you',
        })
        expect(lastCapture(INBOX_EVENTS.VIEWED)?.inbox_client).toBe('cloud')
    })

    it('carries the tab badge counts regardless of the active tab', () => {
        captureInboxViewed({
            tab: 'pulls',
            reports: [],
            totalCount: 0,
            pullsTabCount: 0,
            reportsTabCount: 212,
            hasActiveFilters: false,
            sourceProductFilter: [],
            priorityFilter: [],
            scope: 'for-you',
        })
        expect(lastCapture(INBOX_EVENTS.VIEWED)).toMatchObject({
            tab: 'pulls',
            total_count: 0,
            pulls_tab_count: 0,
            reports_tab_count: 212,
        })
    })

    it('breaks the visible reports down by priority and actionability', () => {
        captureInboxViewed({
            tab: 'reports',
            reports: [
                makeReport({ id: 'a', priority: 'P0', actionability: 'immediately_actionable' }),
                makeReport({ id: 'b', priority: 'P1', actionability: 'requires_human_input' }),
                makeReport({ id: 'c', priority: null, actionability: null }),
            ],
            totalCount: 3,
            pullsTabCount: 1,
            reportsTabCount: 3,
            hasActiveFilters: true,
            sourceProductFilter: ['error_tracking'],
            priorityFilter: ['P0'],
            scope: 'entire-project',
        })
        const props = lastCapture(INBOX_EVENTS.VIEWED)
        expect(props).toMatchObject({
            report_count: 3,
            total_count: 3,
            is_empty: false,
            has_active_filters: true,
            source_product_filter: ['error_tracking'],
            priority_p0_count: 1,
            priority_p1_count: 1,
            priority_unknown_count: 1,
            actionability_immediately_actionable_count: 1,
            actionability_requires_human_input_count: 1,
            actionability_unknown_count: 1,
        })
    })

    it('logs one impression per shown report with its rank and render-time snapshot', () => {
        captureInboxReportsImpressed({
            tab: 'reports',
            reports: [
                makeReport({ id: 'a', priority: 'P0', signal_count: 3, is_suggested_reviewer: true }),
                makeReport({ id: 'b', priority: null, actionability: null, source_products: ['error_tracking'] }),
            ],
            ranks: [1, 2],
            listSize: 2,
            totalCount: 10,
            hasActiveFilters: false,
            scope: 'for-you',
        })
        const props = lastCapture(INBOX_EVENTS.REPORTS_IMPRESSED)
        expect(props).toMatchObject({
            tab: 'reports',
            list_size: 2,
            total_count: 10,
            impression_count: 2,
        })
        expect(props?.impressions).toEqual([
            expect.objectContaining({
                report_id: 'a',
                rank: 1,
                priority: 'P0',
                signal_count: 3,
                is_suggested_reviewer: true,
            }),
            expect.objectContaining({
                report_id: 'b',
                rank: 2,
                priority: null,
                actionability: null,
                source_products: ['error_tracking'],
            }),
        ])
    })

    it('emits a single-report action with the report context', () => {
        captureInboxReportAction({
            report: makeReport(),
            actionType: 'create_pr',
            surface: 'detail_pane',
        })
        expect(lastCapture(INBOX_EVENTS.REPORT_ACTION)).toMatchObject({
            report_id: 'r1',
            action_type: 'create_pr',
            surface: 'detail_pane',
            is_bulk: false,
            bulk_size: 1,
        })
    })

    it('emits a bulk action with a null report and the selection size', () => {
        captureInboxReportAction({
            actionType: 'dismiss',
            surface: 'bulk_bar',
            isBulk: true,
            bulkSize: 4,
            extra: { dismissal_reason: 'wontfix_irrelevant' },
        })
        expect(lastCapture(INBOX_EVENTS.REPORT_ACTION)).toMatchObject({
            report_id: null,
            action_type: 'dismiss',
            surface: 'bulk_bar',
            is_bulk: true,
            bulk_size: 4,
            dismissal_reason: 'wontfix_irrelevant',
        })
    })

    it('carries the dwell before a detail-pane scroll, without the report title', () => {
        captureInboxReportScrolled({
            report: makeReport({ id: 'r9' }),
            rank: 3,
            listSize: 20,
            timeSinceOpenMs: 6200,
        })
        const props = lastCapture(INBOX_EVENTS.REPORT_SCROLLED)
        expect(props).toMatchObject({
            report_id: 'r9',
            rank: 3,
            list_size: 20,
            time_since_open_ms: 6200,
        })
        expect(props?.report_title).toBeUndefined()
        expect(JSON.stringify(props)).not.toContain('Something broke')
    })

    it('records how the query moved without shipping what was typed into the search box', () => {
        captureInboxQueryChanged({
            change: 'search',
            tab: 'reports',
            scope: 'entire-project',
            sortField: 'created_at',
            sortDirection: 'desc',
            sourceProductFilter: ['error_tracking'],
            scoutFilter: [],
            priorityFilter: ['P0'],
            searchQuery: '  acme checkout crash  ',
            hasActiveFilters: true,
        })
        const props = lastCapture(INBOX_EVENTS.QUERY_CHANGED)
        expect(props).toMatchObject({
            change: 'search',
            tab: 'reports',
            scope: 'entire-project',
            sort_field: 'created_at',
            source_product_filter: ['error_tracking'],
            has_search: true,
            search_length: 'acme checkout crash'.length,
        })
        expect(JSON.stringify(props)).not.toContain('acme')
    })

    // A settings value can be a collection of the customer's own names — the base-branch overrides
    // map their repositories, a Slack destination names their channel. Only its size may leave.
    it.each<[string, unknown, unknown, number | null]>([
        ['a scalar', false, false, null],
        ['a repo map', { 'acme/web': 'release', 'acme/api': 'main' }, null, 2],
        ['an empty map', {}, null, 0],
    ])('sends %s as a settings value', (_name, newValue, expectedValue, expectedSize) => {
        captureInboxSettingsChanged({ setting: 'autostart_base_branches', newValue, success: true, scope: 'team' })
        const props = lastCapture(INBOX_EVENTS.SETTINGS_CHANGED)
        expect(props).toMatchObject({ new_value: expectedValue, new_value_size: expectedSize })
        expect(JSON.stringify(props)).not.toContain('acme')
    })

    it('reduces a structured scout setting to its size on both sides of the change', () => {
        captureScoutConfigChanged({
            skillName: 'signals-scout-general',
            scoutOrigin: 'canonical',
            setting: 'output_destinations',
            oldValue: {},
            newValue: { slack: { integration_id: 3, channel: 'acme-alerts' } },
            success: true,
        })
        const props = lastCapture(INBOX_EVENTS.SCOUT_CONFIG_CHANGED)
        expect(props).toMatchObject({
            skill_name: 'signals-scout-general',
            scout_origin: 'canonical',
            setting: 'output_destinations',
            old_value: null,
            old_value_size: 0,
            new_value: null,
            new_value_size: 1,
            success: true,
        })
        expect(JSON.stringify(props)).not.toContain('acme-alerts')
    })

    it('sends an unload close instantly so the dwell time leaves before the page does', () => {
        captureInboxReportClosed(
            { report: makeReport(), timeSpentMs: 4200, closeMethod: 'page_unload' },
            { send_instantly: true }
        )
        const call = (posthog.capture as jest.Mock).mock.calls.find(([name]) => name === INBOX_EVENTS.REPORT_CLOSED)
        expect(call?.[1]).toMatchObject({ close_method: 'page_unload', time_spent_ms: 4200 })
        expect(call?.[2]).toEqual({ send_instantly: true })
    })

    it('records a connected source with first-connection and wizard flags', () => {
        captureSignalSourceConnected({
            sourceProduct: 'github',
            sourceType: 'issue',
            isFirstConnection: true,
            viaSetupWizard: true,
        })
        expect(lastCapture(INBOX_EVENTS.SOURCE_CONNECTED)).toMatchObject({
            source_product: 'github',
            source_type: 'issue',
            is_first_connection: true,
            via_setup_wizard: true,
        })
    })
})
