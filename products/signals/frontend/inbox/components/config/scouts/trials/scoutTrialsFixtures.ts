import type {
    ScoutTrialComparisonApi,
    ScoutTrialResultApi,
    ScoutTrialEvaluationApi,
    ScoutTrialSetupApi,
    SignalScoutConfigApi,
    TrialComparisonReportApi,
} from 'products/signals/frontend/generated/api.schemas'

import { scoutRubricReferenceFixture } from '../scoutRubricFixtures'
import type { ScoutTrialComparison } from './scoutTrialUtils'

export const trialFixtureConfig: SignalScoutConfigApi = {
    id: '00000000-0000-4000-8000-000000000001',
    skill_name: 'signals-scout-checkout-quality',
    display_name: 'Checkout quality',
    description: 'Find recurring checkout issues in product feedback.',
    deprecation: null,
    scout_origin: 'custom',
    scout_role: 'specialist',
    managed_by: 'team',
    owners: [],
    enabled: true,
    status: 'active',
    pause_reason: null,
    emit: true,
    run_interval_minutes: 1440,
    run_cron_schedule: null,
    output_destinations: {},
    structured_output_schema: null,
    network_access: 'trusted',
    model: 'gpt-5.6-terra',
    last_run_at: null,
    consecutive_failure_count: 0,
    status_changed_at: null,
    status_changed_by: null,
    auto_pause_exempt: false,
    tags: [],
    mcp_gateway_server_ids: [],
    write_scopes: [],
    source_product: null,
    source_id: null,
    created_at: '2026-01-01T09:00:00Z',
    updated_at: '2026-01-01T09:00:00Z',
}

export const trialFixtureSetup: ScoutTrialSetupApi = {
    config_id: trialFixtureConfig.id,
    skill_name: trialFixtureConfig.skill_name,
    skill_version: 3,
    skill_body: 'Review product feedback for recurring checkout failures. Confirm the evidence before filing a report.',
    ready: true,
    blocked_reason: null,
    model: 'gpt-5.6-terra',
    reasoning_effort: 'medium',
    models: [
        { model: 'gpt-5.6-luna', reasoning_efforts: ['low', 'medium', 'high'] },
        { model: 'gpt-5.6-terra', reasoning_efforts: ['low', 'medium', 'high'] },
        { model: 'gpt-5.6-sol', reasoning_efforts: ['low', 'medium', 'high'] },
    ],
}

export const trialFixtureResult: ScoutTrialResultApi = {
    launch_id: '00000000-0000-4000-8000-000000000002',
    context_id: '00000000-0000-4000-8000-000000000003',
    model: 'gpt-5.6-terra',
    reasoning_effort: 'medium',
    skill_body_sha256: 'a'.repeat(64),
    result_key: null,
    export_error: null,
    started_at: '2026-01-01T10:00:00Z',
    completed_at: '2026-01-01T10:04:00Z',
    run_id: '00000000-0000-4000-8000-000000000004',
    task_id: '00000000-0000-4000-8000-000000000005',
    task_run_id: '00000000-0000-4000-8000-000000000006',
    status: 'completed',
    task_status: 'completed',
    error: null,
    summary:
        'Reviewed recent checkout feedback and checked related events. Captured one report with reproducible evidence.',
    invalid_reason: null,
    reports: [
        {
            id: '00000000-0000-4000-8000-000000000007',
            document: {
                title: 'Coupon removal clears the delivery choice',
                content:
                    'Removing a coupon also resets the selected delivery option. Three synthetic feedback events describe the same sequence.\n\nReproduce by selecting express delivery, applying a coupon, and removing it before payment.',
            },
        },
    ],
    memory: {
        'finding:checkout:delivery-reset': {
            key: 'finding:checkout:delivery-reset',
            content: 'Investigated delivery selection reset after coupon removal.',
            created_at: '2026-01-01T10:03:00Z',
            updated_at: '2026-01-01T10:03:00Z',
            created_by_run_id: '00000000-0000-4000-8000-000000000004',
        },
    },
    cost_usd: null,
    input_tokens: 18500,
    output_tokens: 2400,
}

export const trialFixtureComparison: ScoutTrialComparison = {
    id: '00000000-0000-4000-8000-000000000020',
    configId: trialFixtureConfig.id,
    baselineVariantId: '00000000-0000-4000-8000-000000000021',
    groups: [
        {
            variantId: '00000000-0000-4000-8000-000000000021',
            launchIds: [trialFixtureResult.launch_id, '00000000-0000-4000-8000-000000000022'],
        },
        {
            variantId: '00000000-0000-4000-8000-000000000023',
            launchIds: ['00000000-0000-4000-8000-000000000024', '00000000-0000-4000-8000-000000000025'],
        },
    ],
}

export const trialFixtureReport: TrialComparisonReportApi = {
    version: 1,
    evaluation_id: trialFixtureComparison.id,
    context_id: trialFixtureResult.context_id,
    created_at: '2026-01-01T10:05:00Z',
    completed_at: '2026-01-01T10:06:00Z',
    summary:
        'The candidate passed both criteria in each repeat. The baseline missed one evidence citation. These four runs are a descriptive comparison.',
    outcome: {
        status: 'winner',
        variant_ids: [trialFixtureComparison.groups[1].variantId],
        summary:
            'Candidate prompt passed 4 of 4 rubric checks; Baseline passed 3 of 4. Each variant ran twice, and every applicable check was judged.',
    },
    rubric_source: 'saved',
    rubric_revision: 1,
    rubric_reference_context: null,
    rubric_reference_generation_id: null,
    baseline_variant_id: trialFixtureComparison.baselineVariantId,
    judge_model: 'gpt-6-astra',
    judge_prompt_version: 'sandbox-1',
    criteria: [
        {
            id: 'evidence',
            title: 'Evidence grounding',
            description: 'Findings cite the observed behavior.',
            pass_condition: 'The finding includes a source supporting the claim.',
            applicability: 'A finding is reported.',
        },
        {
            id: 'action',
            title: 'Useful next step',
            description: 'The report gives a concrete next step.',
            pass_condition: 'The next step can confirm or address the observed issue.',
            applicability: 'A finding is reported.',
        },
    ],
    variants: trialFixtureComparison.groups.map((group, index) => ({
        variant_id: group.variantId,
        label: index === 0 ? 'Baseline' : 'Candidate prompt',
        is_baseline: index === 0,
        total_runs: 2,
        judged_runs: 2,
        excluded_runs: 0,
        judge_errors: 0,
        score: index === 0 ? 0.75 : 1,
        coverage: 1,
        baseline_delta: index === 0 ? null : 0.25,
        criteria: ['evidence', 'action'].map((id) => ({
            criterion_id: id,
            passed: index === 0 && id === 'evidence' ? 1 : 2,
            failed: index === 0 && id === 'evidence' ? 1 : 0,
            unknown: 0,
            not_applicable: 0,
            pass_rate: index === 0 && id === 'evidence' ? 0.5 : 1,
            coverage: 1,
            baseline_delta: index === 0 ? null : id === 'evidence' ? 0.5 : 0,
        })),
    })),
    runs: trialFixtureComparison.groups.flatMap((group, variantIndex) =>
        group.launchIds.map((launchId, repeat) => ({
            launch_id: launchId,
            variant_id: group.variantId,
            status: 'judged',
            score: variantIndex === 0 && repeat === 0 ? 0.5 : 1,
            coverage: 1,
            summary:
                'The report identifies a checkout issue and suggests checking the delivery selection after removing a coupon.',
            criteria: ['evidence', 'action'].map((id) => ({
                criterion_id: id,
                verdict: variantIndex === 0 && repeat === 0 && id === 'evidence' ? 'fail' : 'pass',
                confidence: 'high',
                reason:
                    variantIndex === 0 && repeat === 0 && id === 'evidence'
                        ? 'The report makes the claim without a source reference.'
                        : 'The captured report supports this criterion.',
                evidence: [{ source_id: 'report:1', quote: 'Check the delivery selection after removing a coupon.' }],
            })),
            error: null,
            input_tokens: 1800,
            output_tokens: 300,
        }))
    ),
    evidence: trialFixtureComparison.groups.flatMap((group, variantIndex) =>
        group.launchIds.map((launchId) => ({
            launch_id: launchId,
            variant_id: group.variantId,
            run_id: trialFixtureResult.run_id,
            task_id: trialFixtureResult.task_id,
            task_run_id: trialFixtureResult.task_run_id,
            execution_status: 'completed',
            model: trialFixtureResult.model,
            runtime_adapter: 'codex',
            service_tier: null,
            reasoning_effort: trialFixtureResult.reasoning_effort,
            skill_body_sha256: variantIndex === 0 ? trialFixtureResult.skill_body_sha256 : 'b'.repeat(64),
            input_tokens: 18500,
            output_tokens: 2400,
            sources: [
                { id: 'report:1', kind: 'report', text: 'Check the delivery selection after removing a coupon.' },
            ],
            limitations: ['Tool execution traces were not available for this run.'],
        }))
    ),
    limitations: ['Live data may change between runs. The saved rubric stays fixed across variants.'],
}

export const trialFixtureEvaluation: ScoutTrialEvaluationApi = {
    evaluation_id: trialFixtureReport.evaluation_id,
    context_id: trialFixtureReport.context_id,
    status: 'completed',
    error: null,
    request: {
        evaluation_id: trialFixtureComparison.id,
        baseline_variant_id: trialFixtureComparison.baselineVariantId,
        rubric_source: 'saved',
        variants: trialFixtureComparison.groups.map((group, index) => ({
            id: group.variantId,
            label: index === 0 ? 'Baseline' : 'Candidate prompt',
            launch_ids: group.launchIds,
        })),
    },
    report: trialFixtureReport,
}

export const trialFixtureEvaluationWithJudgeError: ScoutTrialEvaluationApi = {
    ...trialFixtureEvaluation,
    report: {
        ...trialFixtureReport,
        summary: 'One candidate repeat could not be judged. Its score cannot be compared with the baseline.',
        outcome: {
            status: 'inconclusive',
            variant_ids: [],
            summary:
                'One candidate run could not be judged. A complete comparison is needed to identify the best variant.',
        },
        variants: trialFixtureReport.variants.map((variant) =>
            variant.is_baseline
                ? variant
                : {
                      ...variant,
                      judged_runs: 1,
                      judge_errors: 1,
                      baseline_delta: null,
                      criteria: variant.criteria.map((criterion) => ({
                          ...criterion,
                          passed: 1,
                          baseline_delta: null,
                      })),
                  }
        ),
        runs: trialFixtureReport.runs.map((run, index) =>
            index === 3
                ? {
                      ...run,
                      status: 'judge_error',
                      score: null,
                      coverage: null,
                      criteria: [],
                      error: 'The judge response could not be validated.',
                  }
                : run
        ),
    },
}

export const trialFixtureLongReport: TrialComparisonReportApi = {
    ...trialFixtureReport,
    summary: 'Candidate prompt passed all 24 rubric checks across two runs. Baseline passed 22 of 24.',
    outcome: {
        status: 'winner',
        variant_ids: [trialFixtureComparison.groups[1].variantId],
        summary:
            'Candidate prompt passed 24 of 24 rubric checks; Baseline passed 22 of 24. Each variant ran twice, and every applicable check was judged.',
    },
    rubric_source: 'saved',
    rubric_revision: 2,
    criteria: [
        ...trialFixtureReport.criteria,
        {
            id: 'duplicates',
            title: 'Avoid duplicate findings',
            description: 'Check existing findings before creating another report.',
            pass_condition: 'The scout adds new evidence or reports a distinct issue.',
            applicability: 'An existing finding covers the same product area.',
        },
        {
            id: 'priority',
            title: 'Match priority to impact',
            description: 'Use the observed impact to choose a priority.',
            pass_condition: 'The stated priority agrees with the impact described in the evidence.',
            applicability: 'A finding is reported.',
        },
        {
            id: 'flow',
            title: 'Name the affected user flow',
            description: 'Explain which part of checkout is affected.',
            pass_condition: 'The report identifies the action and resulting behavior.',
            applicability: 'A checkout issue is reported.',
        },
        {
            id: 'dates',
            title: 'Use the requested date range',
            description: 'Keep the investigation within the requested period.',
            pass_condition: 'The queried dates match the requested date range.',
            applicability: 'The scout queries dated events.',
        },
        {
            id: 'impact',
            title: 'Support impact estimates',
            description: 'Back numerical impact claims with the observed data.',
            pass_condition: 'Any numerical estimate can be traced to the captured query results.',
            applicability: 'The report estimates the number of affected checkouts.',
        },
        {
            id: 'recurrence',
            title: 'Distinguish recurring issues',
            description: 'Check whether the same issue appears more than once.',
            pass_condition: 'The report distinguishes repeated behavior from a single observation.',
            applicability: 'Feedback events are available.',
        },
        {
            id: 'recommendation',
            title: 'Keep recommendations within scope',
            description: 'Recommend changes related to the observed checkout issue.',
            pass_condition: 'The proposed next step addresses the reported flow.',
            applicability: 'The report recommends an action.',
        },
        {
            id: 'causality',
            title: 'Separate observation from cause',
            description: 'Avoid stating an unverified cause as fact.',
            pass_condition: 'The report distinguishes observed behavior from explanations that need investigation.',
            applicability: 'The report discusses a possible cause.',
        },
        {
            id: 'read-only',
            title: 'Respect read-only instructions',
            description: 'Investigate without changing project settings.',
            pass_condition: 'No project-setting changes were attempted.',
            applicability: 'The scout is configured for read-only investigation.',
        },
        {
            id: 'sensitive-data',
            title: 'Leave sensitive values out of reports',
            description: 'Describe behavior without copying personal or secret values.',
            pass_condition: 'The report contains no personal contact details or credential values.',
            applicability: 'A finding is reported.',
        },
    ],
    limitations: ['Live data may change between runs. These scores describe the captured sample.'],
}

trialFixtureLongReport.runs = trialFixtureLongReport.runs.map((run, index) => ({
    ...run,
    score: index === 0 ? 10 / 12 : 1,
    criteria: trialFixtureLongReport.criteria.map((criterion) => ({
        criterion_id: criterion.id,
        verdict: index === 0 && ['evidence', 'impact'].includes(criterion.id) ? 'fail' : 'pass',
        confidence: 'high',
        reason:
            index === 0 && ['evidence', 'impact'].includes(criterion.id)
                ? 'The report states that three checkouts were affected, but the captured query result contains only two.'
                : 'The captured scout output satisfies this check.',
        evidence:
            index === 0 && ['evidence', 'impact'].includes(criterion.id)
                ? [
                      {
                          source_id: 'report:1',
                          quote: 'Three checkouts lost their delivery selection after coupon removal.',
                      },
                      { source_id: 'trace:1', quote: 'Affected checkouts: 2.' },
                  ]
                : [{ source_id: 'report:1', quote: 'Check the delivery selection after removing a coupon.' }],
    })),
}))

trialFixtureLongReport.evidence = trialFixtureLongReport.evidence.map((evidence, index) => ({
    ...evidence,
    sources: [
        {
            id: 'report:1',
            kind: 'report',
            text: `${index === 0 ? 'Three' : 'Two'} checkouts lost their delivery selection after coupon removal. Check the delivery selection after removing a coupon.`,
        },
        { id: 'trace:1', kind: 'trace', text: 'Affected checkouts: 2.' },
    ],
    limitations: [],
}))

trialFixtureLongReport.variants = trialFixtureLongReport.variants.map((variant) => ({
    ...variant,
    score: variant.is_baseline ? 11 / 12 : 1,
    baseline_delta: variant.is_baseline ? null : 1 / 12,
    criteria: trialFixtureLongReport.criteria.map((criterion) => ({
        criterion_id: criterion.id,
        passed: variant.is_baseline && ['evidence', 'impact'].includes(criterion.id) ? 1 : 2,
        failed: variant.is_baseline && ['evidence', 'impact'].includes(criterion.id) ? 1 : 0,
        unknown: 0,
        not_applicable: 0,
        pass_rate: variant.is_baseline && ['evidence', 'impact'].includes(criterion.id) ? 0.5 : 1,
        coverage: 1,
        baseline_delta: variant.is_baseline ? null : ['evidence', 'impact'].includes(criterion.id) ? 0.5 : 0,
    })),
}))

export const trialFixtureServerComparison: ScoutTrialComparisonApi = {
    comparison_id: trialFixtureComparison.id,
    config_id: trialFixtureComparison.configId,
    context_id: trialFixtureResult.context_id,
    created_at: trialFixtureResult.started_at!,
    baseline_variant_id: trialFixtureComparison.baselineVariantId,
    rubric_revision: 2,
    variants: trialFixtureComparison.groups.map((group, index) => ({
        id: group.variantId,
        label: index === 0 ? 'Baseline' : 'Candidate prompt',
        launch_ids: group.launchIds,
        model: trialFixtureSetup.model!,
        reasoning_effort: trialFixtureSetup.reasoning_effort!,
        skill_body_sha256: trialFixtureReport.evidence.find((item) => item.launch_id === group.launchIds[0])!
            .skill_body_sha256!,
    })),
    status: 'completed',
    error: null,
    evaluation: {
        ...trialFixtureEvaluation,
        request: { ...trialFixtureEvaluation.request, rubric_source: 'saved' },
        report: {
            ...trialFixtureReport,
            rubric_source: 'saved',
            rubric_revision: 2,
            rubric_reference_context: scoutRubricReferenceFixture,
            rubric_reference_generation_id: '00000000-0000-4000-8000-000000000032',
            limitations: ['Live data may change between runs. These results describe the captured sample.'],
        },
    },
}
