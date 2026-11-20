import { describe, expect, it, vi } from 'vitest'

import { estimateTokens } from '@/lib/estimate-tokens'
import { formatResponse } from '@/lib/response'
import { GENERATED_TOOLS as BILLING_TOOLS } from '@/tools/generated/billing'
import { GENERATED_TOOLS as CORE_TOOLS } from '@/tools/generated/core'
import { GENERATED_TOOLS as LOGS_TOOLS } from '@/tools/generated/logs'
import { GENERATED_TOOLS as PRODUCT_ANALYTICS_TOOLS } from '@/tools/generated/product_analytics'
import { GENERATED_TOOLS as SIGNALS_TOOLS } from '@/tools/generated/signals'
import { GENERATED_TOOLS as WORKFLOWS_TOOLS } from '@/tools/generated/workflows'
import type { Context } from '@/tools/types'

/** Each budget keeps one default page usable in an agent's context, not the size the payload is today. */
const LOGS_TOKEN_BUDGET = 20_000
const INSIGHTS_TOKEN_BUDGET = 18_000
const INBOX_TOKEN_BUDGET = 10_000
const PROJECT_TOKEN_BUDGET = 1_200
const BILLING_TOKEN_BUDGET = 9_000
const WORKFLOW_TOKEN_BUDGET = 5_000

const LOG_ROW_COUNT = 100
const POD_COUNT = 3
const INSIGHT_COUNT = 100
const REPORT_COUNT = 20
const FEATURE_COUNT = 200
const EMAIL_STEP_COUNT = 4

const EMAIL_DESIGN_PATH = 'actions.*.config.inputs.email.value.design'

/** The `UserBasic` keys an agent cannot act on. Name and email stay. */
const STRIPPED_USER_FIELDS = ['uuid', 'distinct_id', 'is_email_verified', 'hedgehog_config']

function createMockContext(result: unknown): Context {
    return {
        api: {
            request: vi.fn().mockResolvedValue(result),
            getProjectBaseUrl: () => 'https://us.posthog.com/project/7',
        },
        stateManager: { getProjectId: async () => 7, getOrgID: async () => 'org-7' },
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

const SETUP_TASK_PRODUCTS = [
    'product_analytics',
    'web_analytics',
    'session_replay',
    'feature_flags',
    'experiments',
    'surveys',
    'error_tracking',
    'data_warehouse',
    'llm_analytics',
    'revenue_analytics',
    'workflows',
    'logs',
]
const SETUP_TASK_STEPS = ['install_sdk', 'send_first_event', 'create_first_item', 'invite_teammate', 'review_results']

function createProject(): Record<string, unknown> {
    return {
        id: 7,
        organization: '0192cccc-0000-7000-8000-000000000001',
        name: 'Widget app',
        logo_media_id: null,
        product_description: 'A widget builder for small teams',
        tags: [],
        created_at: '2026-02-18T18:28:34.858807Z',
        effective_membership_level: 8,
        has_group_types: true,
        group_types: ['company', 'workspace'].map((groupType, index) => ({
            group_type: groupType,
            group_type_index: index,
            name_singular: null,
            name_plural: null,
            detail_dashboard: null,
            default_columns: null,
            created_at: '2026-02-20T10:00:00Z',
        })),
        updated_at: '2026-09-30T10:00:00Z',
        uuid: '0192cccc-0000-7000-8000-000000000007',
        api_token: 'phc_example_public_token',
        app_urls: ['https://app.example.com'],
        anonymize_ips: false,
        completed_snippet_onboarding: true,
        ingested_event: true,
        test_account_filters: [
            { key: 'email', type: 'person', value: '@example.com', operator: 'not_icontains' },
            { key: '$host', type: 'event', value: '^localhost', operator: 'not_regex' },
        ],
        test_account_filters_default_checked: true,
        path_cleaning_filters: [{ alias: '/widgets/:id', regex: '/widgets/\\d+' }],
        is_demo: false,
        timezone: 'Europe/Berlin',
        data_attributes: ['data-attr'],
        person_display_name_properties: ['email', 'name'],
        autocapture_opt_out: false,
        autocapture_exceptions_opt_in: true,
        autocapture_web_vitals_opt_in: true,
        autocapture_web_vitals_allowed_metrics: null,
        autocapture_exceptions_errors_to_ignore: null,
        capture_console_log_opt_in: true,
        capture_performance_opt_in: true,
        session_recording_opt_in: true,
        session_recording_sample_rate: null,
        session_recording_minimum_duration_milliseconds: null,
        session_recording_linked_flag: null,
        session_recording_network_payload_capture_config: null,
        session_recording_masking_config: null,
        session_recording_url_trigger_config: [],
        session_recording_url_blocklist_config: [],
        session_recording_event_trigger_config: [],
        session_recording_trigger_match_type_config: null,
        session_recording_trigger_groups: null,
        session_recording_retention_period: '30d',
        session_replay_config: null,
        survey_config: null,
        access_control: false,
        week_start_day: 1,
        primary_dashboard: 42,
        home_tab_dashboard: null,
        live_events_columns: ['event', 'person', 'url', 'timestamp', 'properties.$browser'],
        recording_domains: null,
        person_on_events_querying_enabled: true,
        inject_web_apps: null,
        extra_settings: null,
        modifiers: null,
        has_completed_onboarding_for: { product_analytics: true, session_replay: true },
        surveys_opt_in: null,
        heatmaps_opt_in: true,
        product_intents: SETUP_TASK_PRODUCTS.map((product, index) => ({
            product_type: product,
            created_at: '2026-02-18T18:30:00.000000Z',
            onboarding_completed_at: index % 2 === 0 ? '2026-02-19T09:00:00.000000Z' : null,
            updated_at: '2026-09-30T10:00:00.000000Z',
        })),
        flags_persistence_default: false,
        receive_org_level_activity_logs: false,
        business_model: 'b2b',
        conversations_enabled: null,
        conversations_settings: null,
        logs_settings: null,
        proactive_tasks_enabled: null,
        available_setup_task_ids: SETUP_TASK_PRODUCTS.flatMap((product) =>
            SETUP_TASK_STEPS.map((step) => `${product}_${step}`)
        ),
        is_pending_deletion: false,
        deletion_scheduled_at: null,
        project_id: 7,
        user_access_level: 'admin',
        managed_viewsets: { revenue_analytics: false },
        flag_evaluations_mode: 0,
        api_host: 'https://us.i.posthog.com',
        revenue_analytics_config: { events: [], filter_test_accounts: false, goals: [] },
        marketing_analytics_config: null,
        customer_analytics_config: null,
        workflows_config: null,
        feature_flag_policy_config: null,
        base_currency: 'USD',
        capture_dead_clicks: false,
        cookieless_server_hash_mode: 0,
        human_friendly_comparison_periods: false,
        feature_flag_confirmation_enabled: false,
        feature_flag_confirmation_message: null,
        default_evaluation_contexts_enabled: false,
        require_evaluation_contexts: false,
        default_data_theme: null,
        onboarding_tasks: Object.fromEntries(
            SETUP_TASK_PRODUCTS.flatMap((product) => SETUP_TASK_STEPS.map((step) => [`${product}_${step}`, 'pending']))
        ),
        web_analytics_pre_aggregated_tables_enabled: false,
    }
}

const BILLING_PRODUCTS = [
    'product_analytics',
    'session_replay',
    'feature_flags',
    'surveys',
    'error_tracking',
    'data_warehouse',
    'llm_analytics',
    'logs',
    'workflows',
    'platform_and_support',
]

function createTiers(): Record<string, unknown>[] {
    return [0, 1, 2, 3, 4, 5].map((index) => ({
        flat_amount_usd: '0',
        unit_amount_usd: index === 0 ? '0' : (0.0005 / index).toFixed(7),
        up_to: index === 5 ? null : 1_000_000 * 10 ** index,
        current_amount_usd: index < 2 ? '12.50' : '0.00',
        current_usage: index < 2 ? 1_000_000 : 0,
        projected_usage: index < 2 ? 1_400_000 : null,
        projected_amount_usd: index < 2 ? '17.50' : null,
    }))
}

function createBillingProduct(key: string): Record<string, unknown> {
    const name = key.replace(/_/g, ' ')
    return {
        name,
        type: key,
        description: `Everything ${name} offers, with generous free usage every month and fair prices after that.`,
        docs_url: `https://posthog.com/docs/${key}`,
        usage_key: `${key}_events`,
        unit: 'event',
        unit_amount_usd: null,
        price_description: null,
        subscribed: true,
        free_allocation: 1_000_000,
        current_usage: 2_000_000,
        projected_usage: 2_800_000,
        current_amount_usd: '12.50',
        projected_amount_usd: '17.50',
        projected_amount_usd_with_limit: '17.50',
        usage_limit: null,
        has_exceeded_limit: false,
        percentage_usage: 0.2,
        tiers: createTiers(),
        addons: [
            {
                name: `${name} boost`,
                type: `${key}_boost`,
                description: `Adds longer retention and priority processing to ${name}, billed on the same usage.`,
                docs_url: `https://posthog.com/docs/${key}/boost`,
                usage_key: `${key}_events`,
                unit: 'event',
                unit_amount_usd: null,
                price_description: null,
                subscribed: false,
                included_with_main_product: false,
                included_if: null,
                current_amount_usd: null,
                current_usage: 0,
                projected_usage: 0,
                projected_amount_usd: null,
                usage_limit: null,
                tiers: createTiers(),
            },
        ],
    }
}

function createBillingOverview(): Record<string, unknown> {
    return {
        customer_id: 'cus_example0000000001',
        billing_plan: 'paid',
        subscription_level: 'paid',
        has_active_subscription: true,
        is_annual_plan_customer: false,
        free_trial_until: null,
        current_total_amount_usd: '125.00',
        current_total_amount_usd_after_discount: '125.00',
        projected_total_amount_usd: '175.00',
        projected_total_amount_usd_after_discount: '175.00',
        projected_total_amount_usd_with_limit: '175.00',
        projected_total_amount_usd_with_limit_after_discount: '175.00',
        discount_amount_usd: null,
        discount_percent: null,
        startup_program_label: null,
        startup_program_label_previous: null,
        external_billing_provider_invoices_url: null,
        products: BILLING_PRODUCTS.map(createBillingProduct),
        available_product_features: Array.from({ length: FEATURE_COUNT }, (_, index) => ({
            key: `${BILLING_PRODUCTS[index % BILLING_PRODUCTS.length]}_feature_${index}`,
            name: `Widget feature ${index}`,
            description: `Lets your team use widget feature ${index} across every project in the organization.`,
            unit: index % 10 === 0 ? 'years' : null,
            limit: index % 10 === 0 ? 7 : null,
            note: null,
            is_plan_default: true,
        })),
        usage_summary: Object.fromEntries(
            BILLING_PRODUCTS.map((key) => [`${key}_events`, { usage: 2_000_000, limit: null }])
        ),
        billing_period: { current_period_start: '2026-10-01', current_period_end: '2026-11-01', interval: 'month' },
        custom_limits_usd: { product_analytics: 500 },
        next_period_custom_limits_usd: {},
        trial: null,
        billing_managed_by_partner: null,
    }
}

/** Compiled bytecode repeats each templated string as a list of string-table chunks. */
function compileTemplate(source: string): unknown[] {
    return ['_H', 1, 32, ...source.match(/.{1,80}/gs)!, 2, 'concat', source.length]
}

function createEmailDesign(step: number): Record<string, unknown> {
    return {
        counters: { u_row: 6, u_column: 6, u_content_text: 8, u_content_button: 2 },
        body: {
            id: `design-${step}`,
            rows: Array.from({ length: 6 }, (_, row) => ({
                id: `row-${step}-${row}`,
                cells: [1],
                columns: [
                    {
                        id: `column-${step}-${row}`,
                        contents: [
                            {
                                id: `text-${step}-${row}`,
                                type: 'text',
                                values: {
                                    containerPadding: '10px',
                                    fontSize: '14px',
                                    lineHeight: '140%',
                                    textAlign: 'left',
                                    linkStyle: { inherit: true, linkColor: '#0000ee', linkUnderline: true },
                                    text: `<p>Step ${step}, paragraph ${row}: here is how to get more out of your widgets this week.</p>`,
                                },
                            },
                        ],
                        values: { backgroundColor: '', padding: '0px', border: {}, borderRadius: '0px' },
                    },
                ],
                values: {
                    backgroundColor: '',
                    columnsBackgroundColor: '',
                    padding: '0px',
                    hideDesktop: false,
                    displayCondition: null,
                },
            })),
            values: { contentWidth: '600px', fontFamily: { label: 'Arial', value: 'arial,helvetica,sans-serif' } },
        },
    }
}

function createEmailHtml(step: number): string {
    const paragraphs = Array.from(
        { length: 6 },
        (_, row) =>
            '<tr><td style="padding:10px;font-size:14px;line-height:140%;font-family:arial,helvetica,sans-serif">' +
            `<p>Step ${step}, paragraph ${row}: here is how to get more out of your widgets this week.</p></td></tr>`
    )
    return `<!doctype html><html><body><table width="600" cellpadding="0" cellspacing="0">${paragraphs.join('')}</table></body></html>`
}

function createEmailStep(step: number): Record<string, unknown> {
    const html = createEmailHtml(step)
    const subject = `Widget tips, part ${step}`
    return {
        id: `email_${step}`,
        name: `Day ${step}: widget tips`,
        description: '',
        type: 'function_email',
        on_error: 'continue',
        created_at: 1_760_000_000_000,
        updated_at: 1_760_000_000_000,
        filters: null,
        config: {
            template_id: 'template-email',
            inputs: {
                email: {
                    value: {
                        to: { email: '{{ person.properties.email }}', name: '' },
                        from: { email: 'hello@example.com', name: 'Widget team', integrationId: 12 },
                        subject,
                        preheader: '',
                        text: '',
                        html,
                        design: createEmailDesign(step),
                    },
                    templating: 'liquid',
                    bytecode: { subject: compileTemplate(subject), html: compileTemplate(html) },
                    order: 0,
                },
            },
        },
    }
}

function createWorkflowActions(): Record<string, unknown>[] {
    const trigger = {
        id: 'trigger_node',
        name: 'Trigger',
        description: '',
        type: 'trigger',
        config: {
            type: 'event',
            filters: {
                events: [{ id: 'signed up', name: 'signed up', type: 'events', order: 0 }],
                bytecode: ['_H', 1, 32, 'signed up', 32, 'event', 1, 1, 11],
            },
        },
    }
    const steps = Array.from({ length: EMAIL_STEP_COUNT }, (_, index) => [
        createEmailStep(index + 1),
        {
            id: `delay_${index + 1}`,
            name: 'Wait a day',
            description: '',
            type: 'delay',
            config: { delay_duration: '1d' },
        },
    ]).flat()
    const exit = { id: 'exit_node', name: 'Exit', description: '', type: 'exit', config: { reason: 'Default exit' } }
    return [trigger, ...steps, exit]
}

function createWorkflow(): Record<string, unknown> {
    const actions = createWorkflowActions()
    return {
        id: '0192dddd-0000-7000-8000-000000000001',
        name: 'Widget onboarding',
        description: 'Tips for new widget builders',
        tags: ['onboarding'],
        version: 12,
        status: 'active',
        origin_product: null,
        created_at: '2026-07-01T09:00:00Z',
        created_by: createUser(1, 'Ada', 'Lovelace'),
        updated_at: '2026-10-01T09:00:00Z',
        trigger: actions[0]!.config,
        trigger_masking: null,
        conversion: null,
        exit_condition: 'exit_only_at_end',
        email_sending_rate_limit: null,
        edges: actions.slice(1).map((action, index) => ({ from: actions[index]!.id, to: action.id, type: 'continue' })),
        actions,
        draft: null,
        abort_action: null,
        variables: [],
        billable_action_types: ['function_email'],
        user_access_level: 'editor',
        last_run: null,
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

    describe('project-get', () => {
        const tool = CORE_TOOLS['project-get']!()

        async function shapeProject(): Promise<Record<string, unknown>> {
            return (await tool.handler(createMockContext(createProject()), tool.schema.parse({}))) as unknown as Record<
                string,
                unknown
            >
        }

        it('keeps the project within the response budget', async () => {
            expect(estimateTokens(formatResponse(await shapeProject()))).toBeLessThan(PROJECT_TOKEN_BUDGET)
        })

        it('keeps the settings the session instructions send agents to read', async () => {
            const project = await shapeProject()

            expect(project).toMatchObject({
                id: 7,
                name: 'Widget app',
                api_token: 'phc_example_public_token',
                api_host: 'https://us.i.posthog.com',
                timezone: 'Europe/Berlin',
                person_on_events_querying_enabled: true,
                test_account_filters_default_checked: true,
                test_account_filters: createProject().test_account_filters,
                session_recording_opt_in: true,
                autocapture_exceptions_opt_in: true,
                heatmaps_opt_in: true,
                revenue_analytics_config: { events: [], filter_test_accounts: false, goals: [] },
            })
            expect((project.product_intents as Record<string, unknown>[])[0]).toEqual({
                product_type: 'product_analytics',
                onboarding_completed_at: '2026-02-19T09:00:00.000000Z',
            })
        })
    })

    describe('billing-overview-get', () => {
        const tool = BILLING_TOOLS['billing-overview-get']!()

        async function shapeBilling(): Promise<Record<string, any>> {
            return (await tool.handler(createMockContext(createBillingOverview()), tool.schema.parse({}))) as Record<
                string,
                any
            >
        }

        it(`keeps ${BILLING_PRODUCTS.length} products and ${FEATURE_COUNT} features within the response budget`, async () => {
            expect(estimateTokens(formatResponse(await shapeBilling()))).toBeLessThan(BILLING_TOKEN_BUDGET)
        })

        it('keeps the feature keys and the usage and spend an agent reports', async () => {
            const billing = await shapeBilling()

            expect(billing.available_product_features[10]).toEqual({
                key: 'product_analytics_feature_10',
                name: 'Widget feature 10',
                unit: 'years',
                limit: 7,
            })
            expect(billing.products[0]).toMatchObject({
                type: 'product_analytics',
                subscribed: true,
                current_usage: 2_000_000,
                projected_amount_usd: '17.50',
                has_exceeded_limit: false,
            })
            expect(billing.custom_limits_usd).toEqual({ product_analytics: 500 })
        })
    })

    describe('workflows-get', () => {
        const tool = WORKFLOWS_TOOLS['workflows-get']!()

        async function shapeWorkflow(params: Record<string, unknown> = {}): Promise<Record<string, any>> {
            return (await tool.handler(
                createMockContext(createWorkflow()),
                tool.schema.parse({ id: createWorkflow().id, ...params })
            )) as Record<string, any>
        }

        it(`keeps a ${EMAIL_STEP_COUNT}-email workflow within the response budget`, async () => {
            expect(estimateTokens(formatResponse(await shapeWorkflow()))).toBeLessThan(WORKFLOW_TOKEN_BUDGET)
        })

        it('keeps the email content and returns the editor design only when expanded', async () => {
            const compact = (await shapeWorkflow()).actions[1].config.inputs.email
            const expanded = (await shapeWorkflow({ expand: [EMAIL_DESIGN_PATH] })).actions[1].config.inputs.email

            expect(compact.value).toMatchObject({ subject: 'Widget tips, part 1', html: createEmailHtml(1) })
            expect(compact.value).not.toHaveProperty('design')
            expect(compact).not.toHaveProperty('bytecode')
            expect(expanded.value.design.body.rows[0].id).toBe('row-1-0')
        })
    })
})
