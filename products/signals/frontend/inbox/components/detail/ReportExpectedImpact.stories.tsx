import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type {
    MetricThresholdConfigApi,
    MonitoringMetricConfigApi,
    SignalReportCheckApi,
} from 'products/signals/frontend/generated/api.schemas'

import { makeReport } from '../../__mocks__/inboxMocks'
import { reportMetricQueryHandler, reportMetricsFixture } from '../../__mocks__/reportMetricMocks'
import { ReportExpectedImpact } from './ReportExpectedImpact'

const metric = reportMetricsFixture[0]
const report = makeReport({ id: 'expected-impact-report', metrics: [metric] })
const check: SignalReportCheckApi = {
    id: 'expected-impact-check',
    title: 'API key validation errors fall to at most 50 in 14 days',
    rationale: 'The form should explain why the key could not be created.',
    kind: 'metric_threshold',
    status: 'pending',
    config: {
        metric_id: metric.metric_id,
        query: metric.query as Record<string, unknown>,
        metric_kind: metric.kind,
        value_format: metric.value_format,
        unit: metric.unit,
        comparison: { operator: 'lte', value: 50 },
        baseline_value: 80,
    },
    approved_at: null,
    next_run_at: '2026-09-12T00:00:00Z',
    soak_minutes: 20160,
    run_interval_minutes: null,
    runs_remaining: 1,
    expires_at: '2026-10-12T00:00:00Z',
    last_run_at: null,
    last_outcome: null,
    last_outcome_reason: null,
    dispatched_at: null,
    consecutive_errors: 0,
    created_at: '2026-08-29T00:00:00Z',
    updated_at: '2026-08-29T00:00:00Z',
}

const monitoringDefinition: MonitoringMetricConfigApi = {
    reference_period_minutes: 10080,
    threshold_scaling: 'linear',
    baseline_period_minutes: 20160,
}
const monitoringConfig: MetricThresholdConfigApi = {
    ...check.config,
    metric_kind: 'occurrences',
    value_format: 'count',
    unit: 'errors',
    comparison: { operator: 'lte', value: 70 },
    baseline_value: 280,
    query: {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            dateRange: { date_from: '-7d', explicitDate: true },
            series: [{ kind: 'EventsNode', event: 'checkout_failed', math: 'total' }],
        },
    },
    monitoring: monitoringDefinition,
}
const monitoringStartedAt = '2026-08-26T00:00:00Z'
const monitoringCheck: SignalReportCheckApi = {
    ...check,
    title: 'Checkout errors stay low',
    config: monitoringConfig,
    status: 'active',
    soak_minutes: 10080,
    run_interval_minutes: 360,
    next_run_at: '2026-08-29T18:00:00Z',
    created_at: '2026-08-25T00:00:00Z',
    monitoring_timing: {
        state: 'scheduled',
        started_at: monitoringStartedAt,
        ends_at: '2026-09-02T00:00:00Z',
        next_measurement_at: '2026-08-29T18:00:00Z',
    },
}
const flagOffCheck: SignalReportCheckApi = {
    ...check,
    title: monitoringCheck.title,
    config: { ...monitoringConfig, monitoring: undefined },
}
const fixedTargetCheck: SignalReportCheckApi = {
    ...monitoringCheck,
    config: { ...monitoringConfig, monitoring: { ...monitoringDefinition, threshold_scaling: 'fixed' } },
}
const rateTargetCheck: SignalReportCheckApi = {
    ...fixedTargetCheck,
    title: 'Checkout conversion recovers',
    config: {
        ...fixedTargetCheck.config,
        metric_kind: 'conversion_rate',
        value_format: 'percentage_scaled',
        unit: null,
        comparison: { operator: 'gte', value: 0.4 },
        baseline_value: 0.34,
        query: reportMetricsFixture[2].query as Record<string, unknown>,
    },
}
const failedCheck: SignalReportCheckApi = {
    ...check,
    status: 'failed',
    last_run_at: '2026-08-29T00:00:00Z',
    last_outcome: 'failed',
}
const rangeCheck: SignalReportCheckApi = {
    ...check,
    config: { ...check.config, comparison: { operator: 'between', bounds: { lower: 50, upper: 100 } } },
}

const meta: Meta<typeof ReportExpectedImpact> = {
    title: 'Scenes-App/Inbox/Detail/Expected impact',
    component: ReportExpectedImpact,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
        mockDate: '2026-08-29T12:00:00Z',
        featureFlags: [FEATURE_FLAGS.SIGNALS_REPORT_CHECKS_REPLACE],
    },
    args: { report, reportUrl: 'https://example.com/report' },
    decorators: [
        (Story, context) =>
            mswDecorator({
                get: {
                    '/api/projects/:id/signals/reports/:reportId/artefacts/': { results: [] },
                    '/api/projects/:id/signals/reports/:reportId/signals/': { signals: [] },
                    '/api/projects/:id/signals/reports/:reportId/checks/': context.parameters.loadFailure
                        ? [500, {}]
                        : {
                              results: [context.parameters.check ?? check],
                          },
                    '/api/projects/:id/signals/reports/available_reviewers/': [],
                },
                post: {
                    '/api/environments/:team_id/query/:kind/': reportMetricQueryHandler,
                    '/api/projects/:id/signals/reports/:reportId/checks/:checkId/approve/': {
                        ...check,
                        approved_at: '2026-08-29T00:00:00Z',
                    },
                },
            })(Story, context),
        (Story, context) => (
            <section
                className={`${context.parameters.narrow ? 'w-[32rem]' : 'w-[48rem]'} max-w-[calc(100vw-4rem)] p-4`}
            >
                <h2 className="text-lg font-semibold">Expected impact</h2>
                <Story />
            </section>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof ReportExpectedImpact>

export const MonitoringDefinitionFlagOff: Story = {
    parameters: {
        check: flagOffCheck,
        featureFlags: { [FEATURE_FLAGS.SIGNALS_REPORT_CHECKS_REPLACE]: true, 'signals-report-monitoring': false },
    },
}

export const MonitoringDefinition: Story = {
    args: { report: { ...report, monitoring_started_at: monitoringStartedAt } },
    parameters: {
        check: monitoringCheck,
        featureFlags: [FEATURE_FLAGS.SIGNALS_REPORT_CHECKS_REPLACE, 'signals-report-monitoring'],
    },
}

export const MonitoringDefinitionNarrow: Story = {
    args: MonitoringDefinition.args,
    parameters: {
        check: monitoringCheck,
        narrow: true,
        featureFlags: [FEATURE_FLAGS.SIGNALS_REPORT_CHECKS_REPLACE, 'signals-report-monitoring'],
    },
}

export const MonitoringFixedTarget: Story = {
    args: MonitoringDefinition.args,
    parameters: {
        check: fixedTargetCheck,
        featureFlags: [FEATURE_FLAGS.SIGNALS_REPORT_CHECKS_REPLACE, 'signals-report-monitoring'],
    },
}

export const MetricCheck: Story = {}
export const MonitoringWindowEnded: Story = {
    args: MonitoringDefinition.args,
    parameters: {
        check: {
            ...monitoringCheck,
            soak_minutes: 4320,
            next_run_at: '2026-08-29T00:00:00Z',
            monitoring_timing: {
                state: 'window_ended',
                started_at: monitoringStartedAt,
                ends_at: '2026-08-29T00:00:00Z',
                next_measurement_at: null,
            },
        },
        featureFlags: [FEATURE_FLAGS.SIGNALS_REPORT_CHECKS_REPLACE, 'signals-report-monitoring'],
    },
}
export const RangeGoal: Story = { parameters: { check: rangeCheck } }
export const Narrow: Story = { parameters: { narrow: true } }
export const Failed: Story = { parameters: { check: failedCheck } }
export const LoadFailure: Story = { parameters: { loadFailure: true } }

export const ReplacementUnavailable: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.SIGNALS_REPORT_CHECKS_REPLACE]: false } },
}

export const MonitoringRateTarget: Story = {
    args: MonitoringDefinition.args,
    parameters: {
        check: rateTargetCheck,
        featureFlags: [FEATURE_FLAGS.SIGNALS_REPORT_CHECKS_REPLACE, 'signals-report-monitoring'],
    },
}
