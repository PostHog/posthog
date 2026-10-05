import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

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
    dispatched_at: null,
    consecutive_errors: 0,
    created_at: '2026-08-29T00:00:00Z',
    updated_at: '2026-08-29T00:00:00Z',
}

const meta: Meta<typeof ReportExpectedImpact> = {
    title: 'Scenes-App/Inbox/Detail/Expected impact',
    component: ReportExpectedImpact,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
        mockDate: '2026-08-29',
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
                              results: [
                                  context.parameters.failed
                                      ? {
                                            ...check,
                                            status: 'failed',
                                            last_run_at: '2026-08-29T00:00:00Z',
                                            last_outcome: 'failed',
                                        }
                                      : context.parameters.rangeGoal
                                        ? {
                                              ...check,
                                              config: {
                                                  ...check.config,
                                                  comparison: {
                                                      operator: 'between',
                                                      bounds: { lower: 50, upper: 100 },
                                                  },
                                              },
                                          }
                                        : check,
                              ],
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

export const MetricCheck: Story = {}
export const RangeGoal: Story = { parameters: { rangeGoal: true } }
export const Narrow: Story = { parameters: { narrow: true } }
export const Failed: Story = { parameters: { failed: true } }
export const LoadFailure: Story = { parameters: { loadFailure: true } }

export const ReplacementUnavailable: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.SIGNALS_REPORT_CHECKS_REPLACE]: false } },
}
