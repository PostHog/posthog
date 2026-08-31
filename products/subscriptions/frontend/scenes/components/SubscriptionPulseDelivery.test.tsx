import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type {
    ArtifactLinkDTOApi,
    EvidenceProvenanceDTOApi,
    OutcomeReadoutHistoryDTOApi,
    PulseRunHistoryDTOApi,
    RunActionHistoryDTOApi,
} from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionPulseDelivery } from './SubscriptionPulseDelivery'

jest.mock('lib/components/TZLabel', () => ({
    TZLabel: ({ time }: { time: string }): JSX.Element => (
        <span data-attr="tz-label" data-time={time}>
            formatted date
        </span>
    ),
}))

const run = (overrides: Partial<PulseRunHistoryDTOApi> = {}): PulseRunHistoryDTOApi => ({
    id: '00000000-0000-4000-8000-000000000001',
    subscription_id: 1,
    delivery_id: '00000000-0000-4000-8000-000000000002',
    status: 'completed',
    started_at: '2026-08-30T10:00:00Z',
    finished_at: '2026-08-30T10:01:00Z',
    task_id: null,
    analysis_task_run_id: null,
    execution_task_run_id: null,
    failure_code: null,
    skip_reason: null,
    deliveries: [],
    actions: [],
    readouts: [],
    ...overrides,
})

const action = (overrides: Partial<RunActionHistoryDTOApi>): RunActionHistoryDTOApi => ({
    id: '00000000-0000-4000-8000-000000000003',
    action_key: 'recommendation-1',
    kind: 'recommendation',
    title: 'Review a funnel',
    rationale: 'A conversion change needs review.',
    expected_impact: 'Find a regression sooner.',
    rank: 1,
    implementation_selected: true,
    status: 'completed',
    why_now: null,
    confidence: null,
    effort: '',
    metric_name: null,
    metric_unit: null,
    metric_direction: null,
    expected_change_type: null,
    expected_change_lower: null,
    expected_change_upper: null,
    readout_after_days: null,
    plan_id: null,
    baseline_value: null,
    baseline_from: null,
    baseline_to: null,
    adoption_status: null,
    adoption_source: null,
    adopted_at: null,
    decision_at: null,
    decided_by_id: null,
    readout_status: null,
    next_readout_at: null,
    evidence: [],
    citations: [],
    build_test_gate: null,
    artifacts: [],
    ...overrides,
})

describe('SubscriptionPulseDelivery', () => {
    afterEach(() => cleanup())
    it('shows outcome readouts before advice and keeps authoritative artifacts read-only', () => {
        const outcome = (verdict: string): OutcomeReadoutHistoryDTOApi => ({
            id: `00000000-0000-4000-8000-00000000000${verdict.length}`,
            plan_id: '00000000-0000-4000-8000-000000000010',
            action_id: '00000000-0000-4000-8000-000000000003',
            recommendation_title: `Readout ${verdict}`,
            metric_name: 'Metric checkout-completion',
            metric_unit: 'count',
            baseline_value: '10',
            baseline_from: '2026-08-01T00:00:00Z',
            baseline_to: '2026-08-07T00:00:00Z',
            observed_value: '12',
            observed_from: '2026-08-08T00:00:00Z',
            observed_to: '2026-08-14T00:00:00Z',
            absolute_delta: '2',
            relative_delta: '20',
            status: 'measured',
            verdict,
            confidence: '0.9',
            failure_code: null,
            artifacts: [],
        })
        render(
            <SubscriptionPulseDelivery
                run={run({
                    readouts: ['improved', 'flat', 'regressed', 'inconclusive'].map(outcome),
                    actions: [
                        action({
                            title: 'Advice only',
                            why_now: 'Conversion fell after the release.',
                            confidence: '0.9',
                            effort: 'Low effort',
                            adoption_status: 'pending',
                            metric_name: 'Checkout conversion',
                            metric_unit: 'percent',
                            metric_direction: 'increase',
                            expected_change_type: 'relative_percent',
                            expected_change_lower: '0.8',
                            expected_change_upper: '1.2',
                            baseline_value: '0.1',
                            readout_after_days: 7,
                        }),
                        action({
                            id: '00000000-0000-4000-8000-000000000004',
                            title: 'Prepared PR',
                            kind: 'draft_pr',
                            build_test_gate: {
                                status: 'passed',
                                completed_at: '2026-08-30T10:01:00Z',
                                failure_code: null,
                                gates: [],
                            },
                            artifacts: [
                                {
                                    kind: 'draft_pr',
                                    status: 'verified',
                                    external_url: 'https://github.com/example-org/example-repo/pull/42',
                                    external_state: 'open',
                                    failure_code: null,
                                    task_id: null,
                                    execution_task_run_id: null,
                                    experiment_id: null,
                                },
                            ],
                        }),
                    ],
                })}
                decisionLoadingIds={{}}
                onDecision={jest.fn()}
            />
        )

        expect(
            screen.getByText('Outcome readouts').compareDocumentPosition(screen.getByText('New recommendations'))
        ).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
        expect(
            screen.getByText('New recommendations').compareDocumentPosition(screen.getByText('Prepared artifacts'))
        ).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
        expect(
            screen.getByText('Prepared artifacts').compareDocumentPosition(screen.getByText('Operational details'))
        ).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
        for (const verdict of ['Improved', 'Flat', 'Regressed', 'Inconclusive']) {
            expect(screen.getByText(verdict)).not.toBeNull()
        }
        for (const label of [
            'Why now',
            'Expected movement',
            'Baseline',
            'Effort: Low effort',
            'Readout 7 days after adoption',
        ]) {
            expect(screen.getAllByText(label).length).toBeGreaterThan(0)
        }
        expect(screen.getByText('Expected movement').parentElement).toHaveTextContent(
            'Expected movement: Checkout conversion: 0.8% to 1.2% higher'
        )
        expect(screen.getAllByText('Prepared')).toHaveLength(1)
        expect(screen.getAllByText('Adopt')).toHaveLength(1)
        expect(screen.getAllByText('Dismiss')).toHaveLength(1)
        expect(screen.getAllByText('Measurement').at(0)?.parentElement).toHaveTextContent(
            'Measurement: Metric checkout-completion (count)'
        )
    })

    it('disables both advice decisions while the request is in flight', () => {
        const onDecision = jest.fn()
        const decisionAction = action({
            id: '00000000-0000-4000-8000-000000000003',
            title: 'Advice only',
            adoption_status: 'pending',
        })
        render(
            <SubscriptionPulseDelivery
                run={run({ actions: [decisionAction] })}
                decisionLoadingIds={{ [decisionAction.id]: true }}
                onDecision={onDecision}
            />
        )

        expect(screen.getAllByText('Saving…').length).toBeGreaterThan(0)
        expect(document.querySelector('[data-attr^="pulse-action-adopt-"]')).toHaveAttribute('aria-disabled', 'true')
        expect(document.querySelector('[data-attr^="pulse-action-dismiss-"]')).toHaveAttribute('aria-disabled', 'true')
    })

    it('wraps advice actions inside a narrow container without reading the viewport', () => {
        const decisionAction = action({
            id: '00000000-0000-4000-8000-000000000003',
            title: 'A recommendation with a deliberately long title for a narrow report panel',
            adoption_status: 'pending',
        })
        const { container } = render(
            <div className="w-64">
                <SubscriptionPulseDelivery
                    run={run({ actions: [decisionAction] })}
                    decisionLoadingIds={{}}
                    onDecision={jest.fn()}
                />
            </div>
        )

        const adopt = container.querySelector('[data-attr^="pulse-action-adopt-"]')
        expect(adopt?.parentElement).toHaveClass('flex-wrap')
    })

    it.each(['adopted', 'dismissed', 'abandoned'])('keeps a %s recommendation read-only', (adoptionStatus) => {
        render(
            <SubscriptionPulseDelivery
                run={run({
                    actions: [action({ title: `${adoptionStatus} recommendation`, adoption_status: adoptionStatus })],
                })}
                decisionLoadingIds={{}}
                onDecision={jest.fn()}
            />
        )

        expect(screen.queryByText('Adopt')).toBeNull()
        expect(screen.queryByText('Dismiss')).toBeNull()
    })

    it('keeps merged artifacts separate from adopted and launched outcome states', () => {
        render(
            <SubscriptionPulseDelivery
                run={run({
                    actions: [
                        action({
                            title: 'Merged artifact',
                            kind: 'draft_pr',
                            adoption_status: 'adopted',
                            adoption_source: 'pull_request_merged',
                            artifacts: [
                                {
                                    kind: 'draft_pr',
                                    status: 'verified',
                                    external_url: null,
                                    external_state: 'merged',
                                    failure_code: null,
                                    task_id: null,
                                    execution_task_run_id: null,
                                    experiment_id: null,
                                },
                            ],
                        }),
                        action({
                            id: '00000000-0000-4000-8000-000000000004',
                            title: 'Launched artifact',
                            kind: 'experiment_draft',
                            adoption_status: 'adopted',
                            adoption_source: 'experiment_launched',
                            artifacts: [
                                {
                                    kind: 'experiment_draft',
                                    status: 'verified',
                                    external_url: null,
                                    external_state: 'open',
                                    failure_code: null,
                                    task_id: null,
                                    execution_task_run_id: null,
                                    experiment_id: 7,
                                },
                            ],
                        }),
                    ],
                })}
                decisionLoadingIds={{}}
                onDecision={jest.fn()}
            />
        )

        expect(screen.getByText('Merged')).not.toBeNull()
        expect(screen.getByText('Launched')).not.toBeNull()
        expect(screen.getAllByText('Adopted')).toHaveLength(2)
        expect(screen.queryByText('Adopt')).toBeNull()
    })

    it('keeps a readout connected to its authoritative artifact and inconclusive next step', () => {
        render(
            <SubscriptionPulseDelivery
                run={run({
                    readouts: [
                        {
                            id: '00000000-0000-4000-8000-000000000005',
                            plan_id: '00000000-0000-4000-8000-000000000006',
                            action_id: '00000000-0000-4000-8000-000000000003',
                            recommendation_title: 'Reduce checkout retries',
                            metric_name: 'Metric checkout-completion',
                            metric_unit: 'count',
                            baseline_value: '40',
                            baseline_from: '2026-08-01T00:00:00Z',
                            baseline_to: '2026-08-07T00:00:00Z',
                            observed_value: null,
                            observed_from: null,
                            observed_to: null,
                            absolute_delta: null,
                            relative_delta: null,
                            status: 'inconclusive',
                            verdict: 'inconclusive',
                            confidence: null,
                            failure_code: 'permissions_lost',
                            artifacts: [
                                {
                                    kind: 'draft_pr',
                                    status: 'verified',
                                    external_url: 'https://github.com/example-org/example-repo/pull/42',
                                    external_state: 'merged',
                                    failure_code: null,
                                    task_id: null,
                                    execution_task_run_id: null,
                                    experiment_id: null,
                                },
                            ],
                        },
                    ],
                })}
                decisionLoadingIds={{}}
            />
        )

        expect(screen.getByText('Merged')).not.toBeNull()
        expect(screen.getByText('View source')).not.toBeNull()
        expect(
            screen.getByText(
                'PostHog no longer has access to the measurement source. Restore access before the next readout.'
            )
        ).not.toBeNull()
    })

    it('shows the complete comparison, including zero movement and both windows', () => {
        render(
            <SubscriptionPulseDelivery
                run={run({
                    readouts: [
                        {
                            id: '00000000-0000-4000-8000-000000000015',
                            plan_id: '00000000-0000-4000-8000-000000000016',
                            action_id: '00000000-0000-4000-8000-000000000003',
                            recommendation_title: 'Keep checkout completion steady',
                            metric_name: 'Metric checkout-completion',
                            metric_unit: 'count',
                            baseline_value: '10',
                            baseline_from: '2026-08-01T00:00:00Z',
                            baseline_to: '2026-08-07T00:00:00Z',
                            observed_value: '10',
                            observed_from: '2026-08-08T00:00:00Z',
                            observed_to: '2026-08-14T00:00:00Z',
                            absolute_delta: '0',
                            relative_delta: '0',
                            status: 'measured',
                            verdict: 'flat',
                            confidence: '0.9',
                            failure_code: null,
                            artifacts: [],
                        },
                    ],
                })}
                decisionLoadingIds={{}}
            />
        )

        expect(screen.getByText('Observed').parentElement).toHaveTextContent('Observed: 10')
        expect(screen.getByText('Absolute movement').parentElement).toHaveTextContent('Absolute movement: 0')
        expect(screen.getByText('Relative movement').parentElement).toHaveTextContent('Relative movement: 0%')
        expect(screen.getByText('Measurement').parentElement).toHaveTextContent(
            'Measurement: Metric checkout-completion (count)'
        )
        expect(screen.getByText('Baseline window').parentElement).toHaveTextContent('formatted date – formatted date')
        expect(screen.getByText('Observed window').parentElement).toHaveTextContent('formatted date – formatted date')
    })

    it('renders a completed run with no recommendations without exposing its report reference', () => {
        render(<SubscriptionPulseDelivery run={run()} onDecision={jest.fn()} decisionLoadingIds={{}} />)

        expect(screen.getByText('Pulse')).not.toBeNull()
        expect(screen.getByText('No recommendations this time.')).not.toBeNull()
        expect(screen.queryByText('private.json')).toBeNull()
    })

    it('renders citations and authoritative build results separately from artifact state', () => {
        const evidence: EvidenceProvenanceDTOApi = {
            tool_name: 'research',
            tool_schema_version: 'v1',
            started_at: '2026-08-30T10:00:00Z',
            completed_at: '2026-08-30T10:01:00Z',
            result_truncated: false,
            error_class: null,
        }
        const artifact: ArtifactLinkDTOApi = {
            kind: 'draft_pr',
            status: 'verified',
            external_url: 'https://github.com/example/example.com/pull/123',
            external_state: 'open',
            failure_code: null,
            task_id: '00000000-0000-4000-8000-000000000004',
            execution_task_run_id: null,
            experiment_id: null,
        }
        render(
            <SubscriptionPulseDelivery
                run={run({
                    actions: [
                        action({
                            id: '00000000-0000-4000-8000-000000000003',
                            action_key: 'recommendation-1',
                            kind: 'draft_pr',
                            title: 'Review a funnel',
                            rationale: 'A conversion change needs review.',
                            expected_impact: 'Find a regression sooner.',
                            rank: 1,
                            implementation_selected: true,
                            status: 'completed',
                            evidence: [evidence],
                            citations: [
                                {
                                    evidence_id: '00000000-0000-4000-8000-000000000005',
                                    canonical_url: 'https://docs.example.org/research',
                                    title: 'Release notes',
                                    retrieved_at: '2026-08-30T10:00:00Z',
                                },
                            ],
                            build_test_gate: {
                                status: 'passed',
                                completed_at: '2026-08-30T10:01:00Z',
                                failure_code: null,
                                gates: [
                                    { label: 'Focused tests', status: 'passed' },
                                    { label: 'Frontend build', status: 'passed' },
                                ],
                            },
                            artifacts: [artifact],
                        }),
                    ],
                })}
                onDecision={jest.fn()}
                decisionLoadingIds={{}}
            />
        )

        expect(screen.queryByText('Release notes')).toBeNull()
        fireEvent.click(screen.getByText('Operational details'))
        expect(screen.getByText('Release notes')).not.toBeNull()
        expect(screen.getByText('Focused tests: Passed · Frontend build: Passed')).not.toBeNull()
        expect(screen.getAllByText('Prepared')).toHaveLength(1)
        expect(screen.getByText('Draft PR is open.')).not.toBeNull()
        expect(screen.getByText('Draft PR')).not.toBeNull()
    })

    it('renders both artifacts for a combined action when PR publication remains unknown', () => {
        render(
            <SubscriptionPulseDelivery
                run={run({
                    status: 'partial',
                    failure_code: 'publication_blocked',
                    actions: [
                        action({
                            id: '00000000-0000-4000-8000-000000000006',
                            action_key: 'combined-checkout-follow-up',
                            kind: 'combined',
                            title: 'Improve checkout recovery and measure it',
                            rationale: 'Checkout failures increased.',
                            expected_impact: 'Reduce failed checkouts.',
                            rank: 1,
                            implementation_selected: true,
                            status: 'failed',
                            evidence: [],
                            citations: [],
                            build_test_gate: null,
                            artifacts: [
                                {
                                    kind: 'draft_pr',
                                    status: 'publication_unknown',
                                    external_url: null,
                                    external_state: 'publication_unknown',
                                    failure_code: null,
                                    task_id: '00000000-0000-4000-8000-000000000007',
                                    execution_task_run_id: null,
                                    experiment_id: null,
                                },
                                {
                                    kind: 'experiment_draft',
                                    status: 'verified',
                                    external_url: null,
                                    external_state: null,
                                    failure_code: null,
                                    task_id: '00000000-0000-4000-8000-000000000008',
                                    execution_task_run_id: null,
                                    experiment_id: 42,
                                },
                            ],
                        }),
                    ],
                })}
                onDecision={jest.fn()}
                decisionLoadingIds={{}}
            />
        )

        expect(screen.getByText('Experiment draft')).not.toBeNull()
        expect(screen.getAllByText('Prepared').length).toBeGreaterThan(0)
        expect(screen.getByText('Draft PR publication status is unknown.')).not.toBeNull()
    })

    it('keeps failed preparation out of recommendations and reports failures operationally', () => {
        render(
            <SubscriptionPulseDelivery
                run={run({
                    actions: [
                        action({
                            id: '00000000-0000-4000-8000-000000000010',
                            kind: 'draft_pr',
                            title: 'Zero artifact preparation',
                            status: 'failed',
                        }),
                        action({
                            id: '00000000-0000-4000-8000-000000000011',
                            kind: 'experiment_draft',
                            title: 'Failed artifact preparation',
                            status: 'failed',
                            artifacts: [
                                {
                                    kind: 'experiment_draft',
                                    status: 'failed',
                                    external_url: null,
                                    external_state: null,
                                    failure_code: 'publication_blocked',
                                    task_id: null,
                                    execution_task_run_id: null,
                                    experiment_id: null,
                                },
                            ],
                        }),
                        action({
                            id: '00000000-0000-4000-8000-000000000012',
                            kind: 'combined',
                            title: 'Mixed preparation',
                            status: 'failed',
                            artifacts: [
                                {
                                    kind: 'draft_pr',
                                    status: 'verified',
                                    external_url: null,
                                    external_state: 'open',
                                    failure_code: null,
                                    task_id: null,
                                    execution_task_run_id: null,
                                    experiment_id: null,
                                },
                                {
                                    kind: 'experiment_draft',
                                    status: 'failed',
                                    external_url: null,
                                    external_state: null,
                                    failure_code: 'publication_blocked',
                                    task_id: null,
                                    execution_task_run_id: null,
                                    experiment_id: null,
                                },
                            ],
                        }),
                    ],
                })}
                decisionLoadingIds={{}}
            />
        )

        expect(screen.queryByText('New recommendations')).toBeNull()
        expect(screen.getByText('Prepared artifacts')).not.toBeNull()
        expect(screen.getByText('Operational details')).not.toBeNull()
        expect(screen.queryByText('Publication was blocked by the safety check.')).toBeNull()
        fireEvent.click(screen.getByText('Operational details'))
        expect(screen.getAllByText('Publication was blocked by the safety check.').length).toBeGreaterThan(0)
    })

    it('renders every adoption and readout lifecycle state separately', () => {
        render(
            <SubscriptionPulseDelivery
                run={run({
                    actions: [
                        ...['pending', 'adopted', 'dismissed', 'abandoned'].map((adoptionStatus, index) =>
                            action({
                                id: `00000000-0000-4000-8000-00000000002${index}`,
                                title: `Adoption ${adoptionStatus}`,
                                adoption_status: adoptionStatus,
                            })
                        ),
                        action({
                            id: '00000000-0000-4000-8000-000000000029',
                            kind: 'draft_pr',
                            title: 'Artifact adoption pending',
                            adoption_status: 'pending',
                            artifacts: [
                                {
                                    kind: 'draft_pr',
                                    status: 'verified',
                                    external_url: null,
                                    external_state: 'open',
                                    failure_code: null,
                                    task_id: null,
                                    execution_task_run_id: null,
                                    experiment_id: null,
                                },
                            ],
                        }),
                        ...['waiting', 'scheduled', 'due', 'measuring', 'measured', 'inconclusive', 'cancelled'].map(
                            (readoutStatus, index) =>
                                action({
                                    id: `00000000-0000-4000-8000-00000000003${index}`,
                                    title: `Readout ${readoutStatus}`,
                                    adoption_status: 'adopted',
                                    readout_status: readoutStatus,
                                    next_readout_at: readoutStatus === 'scheduled' ? '2026-09-01T10:00:00Z' : null,
                                })
                        ),
                    ],
                })}
                decisionLoadingIds={{}}
                onDecision={jest.fn()}
            />
        )

        for (const label of [
            'Decision pending',
            'Adoption pending',
            'Adopted',
            'Dismissed',
            'Abandoned',
            'Readout not scheduled',
            'Readout scheduled',
            'Readout due',
            'Measuring',
            'Measured',
            'Inconclusive',
            'Readout cancelled',
        ]) {
            expect(screen.getAllByText(label).length).toBeGreaterThan(0)
        }
        expect(screen.getByText('formatted date').parentElement).toHaveTextContent('Scheduled for formatted date')
        expect(document.querySelector('[data-attr="tz-label"]')).toHaveAttribute('data-time', '2026-09-01T10:00:00Z')
    })

    it('keeps zero confidence and baseline values visible', () => {
        render(
            <SubscriptionPulseDelivery
                run={run({
                    actions: [
                        action({
                            title: 'Maintain the current rate',
                            confidence: '0',
                            baseline_value: '0',
                        }),
                    ],
                })}
                decisionLoadingIds={{}}
            />
        )

        expect(screen.getByText('Confidence').parentElement).toHaveTextContent('Confidence: 0')
        expect(screen.getByText('Baseline').parentElement).toHaveTextContent('Baseline: 0')
    })

    it('uses readable absolute and relative metric movement copy', () => {
        render(
            <SubscriptionPulseDelivery
                run={run({
                    actions: [
                        action({
                            metric_name: 'Checkout conversion',
                            metric_unit: 'percent',
                            metric_direction: 'decrease',
                            expected_change_type: 'absolute',
                            expected_change_lower: '0.8',
                            expected_change_upper: '1.2',
                        }),
                        action({
                            id: '00000000-0000-4000-8000-000000000040',
                            metric_name: 'Retry events',
                            metric_unit: 'count',
                            metric_direction: 'increase',
                            expected_change_type: 'relative_percent',
                            expected_change_lower: '5',
                            expected_change_upper: '10',
                        }),
                    ],
                })}
                decisionLoadingIds={{}}
            />
        )

        expect(screen.getAllByText('Expected movement')[0].parentElement).toHaveTextContent(
            'Expected movement: Checkout conversion: 0.8 to 1.2 percentage points lower'
        )
        expect(screen.getAllByText('Expected movement')[1].parentElement).toHaveTextContent(
            'Expected movement: Retry events: 5% to 10% higher'
        )
        expect(screen.queryByText(/relative_percent/)).toBeNull()
    })
})
