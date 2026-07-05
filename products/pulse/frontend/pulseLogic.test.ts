import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import type { SubscriptionApi } from '@posthog/products-subscriptions/frontend/generated/api.schemas'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    BriefConfigApi,
    OpportunityApi,
    OpportunityStatusEnumApi,
    ProductBriefApi,
    ProposedExperimentApi,
} from './generated/api.schemas'
import {
    BRIEF_ALREADY_GENERATING_MESSAGE,
    CITATION_TYPES,
    MAX_CONSECUTIVE_POLL_FAILURES,
    parseOpportunityEvidence,
    pulseLogic,
    transitionsForStatus,
} from './pulseLogic'

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn(async () => true),
}))
const { copyToClipboard } = jest.requireMock('lib/utils/copyToClipboard')

const generatingBrief = {
    id: 'brief-1',
    config: null,
    status: 'generating',
    trigger: 'on_demand',
    period_days: 7,
    sections: [],
    sources_used: [],
    error: null,
    my_vote: null,
    helpful_count: 0,
    not_helpful_count: 0,
    created_at: '2026-07-02T10:00:00Z',
    created_by: null,
    updated_at: null,
}

const readyBrief = {
    ...generatingBrief,
    status: 'ready',
    sections: [
        {
            kind: 'what_happened',
            title: 'Signups dipped',
            markdown: 'Signup conversion dropped 12%.',
            citations: ['insight:abc123'],
            confidence: 0.9,
        },
    ],
    sources_used: ['anchored_insights'],
}

const openOpportunity: OpportunityApi = {
    id: 'opp-1',
    kind: 'build',
    status: 'open',
    title: 'Recover the signup drop',
    summary: 's',
    suggested_action: 'a',
    evidence: [{ type: 'insight', ref: 'abc123', label: 'Signups' }],
    goal_relevant: false,
    proposed_experiment: null,
    first_seen_brief: null,
    my_vote: null,
    helpful_count: 0,
    not_helpful_count: 0,
    created_at: '2026-06-01T00:00:00Z',
    created_by: null,
    updated_at: null,
}

const proposedExperiment: ProposedExperimentApi = {
    hypothesis: 'Moving the entry point above the fold lifts subscription creation',
    flag_key_suggestion: 'subscription-entry-point',
    target_metric: { insight_short_id: 'abc123' },
    variant_sketch: 'Control keeps the sidebar entry; test adds a button above the insights list.',
}

const existingConfig: BriefConfigApi = {
    id: 'cfg-1',
    name: 'Flags team',
    focus_prompt: 'flags',
    anchors: { dashboards: [1], insights: ['abc123'] },
    goal: 'Increase subscription usage',
    goal_metric: { insight_short_id: 'abc123' },
    enabled: true,
    created_at: '2026-07-01T00:00:00Z',
    created_by: null,
    updated_at: null,
}

const pulseSubscription = {
    id: 3,
    resource_type: 'pulse_brief',
    pulse_brief_config_id: 'cfg-1',
    target_type: 'email',
    target_value: 'team@posthog.com',
    frequency: 'weekly',
    interval: 1,
    start_date: '2026-07-01T09:00:00Z',
    summary: 'sent every week',
    title: 'Flags team brief',
    deleted: false,
    enabled: true,
} as unknown as SubscriptionApi

describe('pulseLogic', () => {
    let logic: ReturnType<typeof pulseLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/pulse/brief_configs/': { count: 0, results: [] },
                '/api/projects/:team_id/pulse/briefs/': { count: 0, results: [] },
                '/api/projects/:team_id/pulse/briefs/:id/': readyBrief,
                '/api/projects/:team_id/pulse/opportunities/': { count: 0, results: [] },
                '/api/projects/:team_id/subscriptions/': { count: 0, results: [] },
            },
            post: {
                '/api/projects/:team_id/pulse/briefs/generate/': () => [201, generatingBrief],
            },
        })
        initKeaTests()
        copyToClipboard.mockClear()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PULSE], { [FEATURE_FLAGS.PULSE]: true })
        logic = pulseLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('generates a brief, polls it, and stops polling on terminal status', async () => {
        await expectLogic(logic, () => {
            logic.actions.generateBrief({ configId: null })
        })
            .toDispatchActions(['generateBriefSuccess', 'startPolling'])
            .toMatchValues({
                selectedBriefId: 'brief-1',
                isGeneratingForSelectedConfig: true,
            })

        // A poll tick that finds the brief in a terminal state merges it in.
        await expectLogic(logic, () => {
            logic.actions.pollGeneratingBriefs()
        })
            .toDispatchActions(['briefsRefreshed'])
            .toMatchValues({ isGeneratingForSelectedConfig: false })
        expect(logic.values.briefs[0].status).toEqual('ready')
        expect(logic.values.briefDetail?.sections).toHaveLength(1)

        // The next tick finds nothing generating: it stops the interval without fetching.
        await expectLogic(logic, () => {
            logic.actions.pollGeneratingBriefs()
        })
            .toDispatchActions(['stopPolling'])
            .toNotHaveDispatchedActions(['briefsRefreshed'])
    })

    it('stops polling with an error toast after consecutive all-failed poll rounds', async () => {
        const errorSpy = jest.spyOn(lemonToast, 'error')
        useMocks({
            get: { '/api/projects/:team_id/pulse/briefs/:id/': () => [500, {}] },
        })

        await expectLogic(logic, () => {
            logic.actions.generateBrief({ configId: null })
        }).toDispatchActions(['startPolling'])

        for (let round = 1; round < MAX_CONSECUTIVE_POLL_FAILURES; round++) {
            await expectLogic(logic, () => {
                logic.actions.pollGeneratingBriefs()
            })
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['stopPolling'])
        }

        // The failure ceiling stops the interval and surfaces the stuck state.
        await expectLogic(logic, () => {
            logic.actions.pollGeneratingBriefs()
        })
            .toFinishAllListeners()
            .toDispatchActions(['stopPolling'])
        expect(errorSpy).toHaveBeenCalled()
        expect(logic.values.briefs[0].status).toEqual('generating')
    })

    it('surfaces the consent banner on an AI data processing 400 without starting polling', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/briefs/generate/': () => [
                    400,
                    {
                        type: 'validation_error',
                        code: 'ai_consent_required',
                        detail: 'AI data processing must be approved for this organization to generate briefs.',
                        attr: null,
                    },
                ],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.generateBrief({ configId: null })
        })
            .toFinishAllListeners()
            .toMatchValues({
                aiConsentRequired: true,
                generatedBrief: null,
                briefs: [],
            })
        await expectLogic(logic).toNotHaveDispatchedActions(['startPolling'])
    })

    it('toasts on a 409 generation conflict without touching the brief list', async () => {
        silenceKeaLoadersErrors()
        const infoSpy = jest.spyOn(lemonToast, 'info')
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/briefs/generate/': () => [
                    409,
                    { detail: 'Brief generation already in progress' },
                ],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.generateBrief({ configId: null })
        })
            .toDispatchActions(['generateBriefFailure'])
            .toMatchValues({
                aiConsentRequired: false,
                briefs: [],
            })
        expect(infoSpy).toHaveBeenCalledWith(BRIEF_ALREADY_GENERATING_MESSAGE)
        await expectLogic(logic).toNotHaveDispatchedActions(['startPolling'])
        resumeKeaLoadersErrors()
    })

    it.each<
        [
            string,
            BriefConfigApi | null,
            'post' | 'patch',
            Record<string, unknown>,
            Record<string, unknown>,
            { goal: string; goal_metric: Record<string, string> | null },
        ]
    >([
        [
            'create',
            null,
            'post',
            { dashboards: [2] },
            // Whitespace-only entries must clear to null, and real entries must be trimmed.
            { goal: '  Grow usage ', goal_metric_short_id: '  NewMetric1 ' },
            { goal: 'Grow usage', goal_metric: { insight_short_id: 'NewMetric1' } },
        ],
        // Insight anchors set through the API must survive a save from this dashboards-only form,
        // and the goal fields seeded from the config must round-trip unchanged.
        [
            'edit',
            existingConfig,
            'patch',
            { dashboards: [2], insights: ['abc123'] },
            {},
            { goal: 'Increase subscription usage', goal_metric: { insight_short_id: 'abc123' } },
        ],
        [
            'edit clearing the goal metric',
            existingConfig,
            'patch',
            { dashboards: [2], insights: ['abc123'] },
            { goal_metric_short_id: '   ' },
            { goal: 'Increase subscription usage', goal_metric: null },
        ],
    ])(
        'saving a config in %s mode hits the %s endpoint with the form payload',
        async (_mode, editing, endpoint, expectedAnchors, extraFormValues, expectedGoalPayload) => {
            const captured: Record<'post' | 'patch', Record<string, any> | null> = { post: null, patch: null }
            useMocks({
                post: {
                    '/api/projects/:team_id/pulse/brief_configs/': async (info) => {
                        captured.post = (await info.request.json()) as Record<string, any>
                        return [201, { ...existingConfig, ...captured.post, id: 'cfg-new' }]
                    },
                },
                patch: {
                    '/api/projects/:team_id/pulse/brief_configs/:id/': async (info) => {
                        captured.patch = (await info.request.json()) as Record<string, any>
                        return [200, { ...existingConfig, ...captured.patch }]
                    },
                },
            })

            logic.actions.openConfigModal(editing)
            logic.actions.setConfigFormValues({ name: 'Updated name', dashboards: [2], ...extraFormValues })
            await expectLogic(logic, () => {
                logic.actions.submitConfigForm()
            }).toDispatchActions(['configSaved'])

            expect(captured[endpoint === 'post' ? 'patch' : 'post']).toBeNull()
            expect(captured[endpoint]!.name).toEqual('Updated name')
            expect(captured[endpoint]!.anchors).toEqual(expectedAnchors)
            expect(captured[endpoint]!.goal).toEqual(expectedGoalPayload.goal)
            expect(captured[endpoint]!.goal_metric).toEqual(expectedGoalPayload.goal_metric)
        }
    )

    it('exposes the goal of the shown brief config for the detail header line', async () => {
        await expectLogic(logic).toFinishAllListeners() // let the mount-time loads settle before seeding
        logic.actions.loadBriefConfigsSuccess([existingConfig, { ...existingConfig, id: 'cfg-2', goal: '   ' }])

        logic.actions.loadBriefDetailSuccess({ ...readyBrief, config: 'cfg-1' } as unknown as ProductBriefApi)
        expect(logic.values.briefDetailGoal).toEqual('Increase subscription usage')

        // A whitespace-only goal must not render an empty header line.
        logic.actions.loadBriefDetailSuccess({ ...readyBrief, config: 'cfg-2' } as unknown as ProductBriefApi)
        expect(logic.values.briefDetailGoal).toBeNull()

        // Config-less briefs have no goal line.
        logic.actions.loadBriefDetailSuccess(readyBrief as unknown as ProductBriefApi)
        expect(logic.values.briefDetailGoal).toBeNull()
    })

    it('narrows malformed investigation entries instead of crashing the detail view', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadBriefDetailSuccess({
            ...readyBrief,
            investigation: [
                { question: 'What is the CTR?', hogql: 'SELECT 1', result_summary: '0.42', succeeded: true },
                { question: 42, succeeded: 'yes' },
                // A replay finding: session citations narrowed to strings, non-strings dropped.
                {
                    question: 'Why the drop?',
                    hogql: '',
                    result_summary: 'Watched 12 sessions',
                    succeeded: true,
                    citations: ['session:s1', 42, 'session:s2'],
                },
            ],
        } as unknown as ProductBriefApi)
        expect(logic.values.briefDetailInvestigation).toEqual([
            { question: 'What is the CTR?', hogql: 'SELECT 1', result_summary: '0.42', succeeded: true, citations: [] },
            { question: '', hogql: '', result_summary: '', succeeded: false, citations: [] },
            {
                question: 'Why the drop?',
                hogql: '',
                result_summary: 'Watched 12 sessions',
                succeeded: true,
                citations: ['session:s1', 'session:s2'],
            },
        ])
    })

    it('schedules a brief for the config being edited', async () => {
        let captured: Record<string, any> | null = null
        useMocks({
            post: {
                '/api/projects/:team_id/subscriptions/': async (info) => {
                    captured = (await info.request.json()) as Record<string, any>
                    return [201, { ...pulseSubscription, target_value: captured.target_value }]
                },
            },
        })

        logic.actions.openConfigModal(existingConfig)
        logic.actions.setScheduleFormValues({ frequency: 'daily', target_value: 'a@posthog.com,b@posthog.com' })
        await expectLogic(logic, () => {
            logic.actions.submitScheduleForm()
        }).toDispatchActions(['briefScheduled'])

        expect(captured!.pulse_brief_config_id).toEqual('cfg-1')
        expect(captured!.frequency).toEqual('daily')
        expect(captured!.target_value).toEqual('a@posthog.com,b@posthog.com')
        expect(logic.values.editingConfigSubscription?.id).toEqual(pulseSubscription.id)
    })

    it.each<[string, string]>([
        ['no emails', ''],
        ['an invalid email', 'not-an-email'],
    ])('blocks scheduling with %s before any request is made', async (_name, target_value) => {
        let requested = false
        useMocks({
            post: {
                '/api/projects/:team_id/subscriptions/': () => {
                    requested = true
                    return [201, pulseSubscription]
                },
            },
        })

        logic.actions.openConfigModal(existingConfig)
        logic.actions.setScheduleFormValues({ target_value })
        await expectLogic(logic, () => {
            logic.actions.submitScheduleForm()
        }).toDispatchActions(['submitScheduleFormFailure'])

        expect(requested).toBe(false)
        expect(logic.values.editingConfigSubscription).toBeNull()
    })

    it('removes the linked schedule via soft delete', async () => {
        let captured: Record<string, any> | null = null
        useMocks({
            patch: {
                '/api/projects/:team_id/subscriptions/:id/': async (info) => {
                    captured = (await info.request.json()) as Record<string, any>
                    return [200, { ...pulseSubscription, deleted: true }]
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners() // let the mount-time loads settle before seeding
        logic.actions.loadBriefSubscriptionsSuccess([pulseSubscription])
        logic.actions.openConfigModal(existingConfig)

        await expectLogic(logic, () => {
            logic.actions.unscheduleBrief(pulseSubscription.id)
        }).toDispatchActions(['briefUnscheduled'])

        expect(captured).toEqual({ deleted: true })
        expect(logic.values.briefSubscriptions).toHaveLength(0)
        expect(logic.values.editingConfigSubscription).toBeNull()
        expect(logic.values.subscriptionIdBeingUnscheduled).toBeNull()
    })

    it('keeps the schedule and clears the unscheduling state when removal fails', async () => {
        const errorSpy = jest.spyOn(lemonToast, 'error')
        useMocks({
            patch: { '/api/projects/:team_id/subscriptions/:id/': () => [500, {}] },
        })
        await expectLogic(logic).toFinishAllListeners() // let the mount-time loads settle before seeding
        logic.actions.loadBriefSubscriptionsSuccess([pulseSubscription])

        await expectLogic(logic, () => {
            logic.actions.unscheduleBrief(pulseSubscription.id)
        })
            .toFinishAllListeners()
            .toMatchValues({ subscriptionIdBeingUnscheduled: null })

        expect(logic.values.briefSubscriptions).toHaveLength(1)
        expect(errorSpy).toHaveBeenCalled()
    })

    it('keeps the config and clears the deleting state when delete fails', async () => {
        const errorSpy = jest.spyOn(lemonToast, 'error')
        useMocks({
            delete: { '/api/projects/:team_id/pulse/brief_configs/:id/': () => [500, {}] },
        })
        await expectLogic(logic).toFinishAllListeners() // let the mount-time loads settle before seeding
        logic.actions.loadBriefConfigsSuccess([existingConfig])

        await expectLogic(logic, () => {
            logic.actions.deleteConfig('cfg-1')
        })
            .toFinishAllListeners()
            .toMatchValues({ configIdBeingDeleted: null })
        expect(logic.values.briefConfigs).toHaveLength(1)
        expect(errorSpy).toHaveBeenCalled()
    })

    it('resets selection when the active config is deleted', async () => {
        useMocks({
            delete: { '/api/projects/:team_id/pulse/brief_configs/:id/': () => [204] },
        })
        await expectLogic(logic).toFinishAllListeners() // let the mount-time loads settle before seeding
        logic.actions.loadBriefConfigsSuccess([existingConfig])
        logic.actions.selectConfig('cfg-1')

        await expectLogic(logic, () => {
            logic.actions.deleteConfig('cfg-1')
        })
            .toDispatchActions(['configDeleted'])
            .toMatchValues({ selectedConfigId: null, briefConfigs: [] })
    })

    it.each([
        [
            'citation without separator',
            { kind: 'k', title: 't', markdown: 'm', citations: ['noseparator'], confidence: 0.5 },
            { kind: 'k', title: 't', markdown: 'm', citations: [{ type: '', ref: 'noseparator' }], confidence: 0.5 },
        ],
        [
            'citation with leading separator',
            { kind: 'k', title: 't', markdown: 'm', citations: [':leading'], confidence: 0.5 },
            { kind: 'k', title: 't', markdown: 'm', citations: [{ type: '', ref: ':leading' }], confidence: 0.5 },
        ],
        [
            'section missing kind, title, and markdown',
            {},
            { kind: '', title: '', markdown: '', citations: [], confidence: 0 },
        ],
        [
            'non-array citations and non-number confidence',
            { kind: 'k', title: 't', markdown: 'm', citations: 'nope', confidence: 'high' },
            { kind: 'k', title: 't', markdown: 'm', citations: [], confidence: 0 },
        ],
    ])('parses malformed brief sections: %s', (_name, section, expected) => {
        logic.actions.loadBriefDetailSuccess({ ...readyBrief, sections: [section] } as unknown as ProductBriefApi)
        expect(logic.values.briefDetailSections[0]).toEqual(expected)
    })

    it.each<[string, string, string | undefined]>([
        ['insight', 'abc123', '/insights/abc123'],
        ['dashboard', '5', '/dashboard/5'],
        ['flag', '123', '/feature_flags/123'],
        ['experiment', '45', '/experiments/45'],
        ['annotation', '77', '/data-management/annotations/77'],
        // Opportunity refs are internal UUIDs — every one links to the opportunities panel.
        ['opportunity', '11111111-1111-1111-1111-111111111111', '/pulse?tab=opportunities'],
        // A hallucinated non-numeric ref renders unlinked instead of a dead /NaN link.
        ['flag', 'not-a-number', undefined],
        // Empty-string and "0" are finite numbers but not real ids — must not link to resource 0.
        ['flag', '', undefined],
        ['experiment', '0', undefined],
        // Session refs are opaque strings (no numeric guard) linking to the replay player.
        ['session', 'abc-123', '/replay/abc-123'],
    ])('maps %s:%s citations to a scene URL', (type, ref, expected) => {
        expect(CITATION_TYPES[type].url?.(ref)).toEqual(expected)
    })

    it('parses opportunity evidence entries, dropping malformed ones', () => {
        expect(
            parseOpportunityEvidence([
                { type: 'insight', ref: 'abc123', label: 'Signups' },
                { type: 42, ref: 'x' },
                { type: 'insight' },
            ])
        ).toEqual([
            { type: 'insight', ref: 'abc123' },
            { type: '', ref: 'x' },
        ])
    })

    it.each<[string, string[]]>([
        ['open', ['acted', 'dismiss']],
        ['dismissed', ['reopen']],
        ['acted', []],
        ['resolved', []],
    ])('offers the right transitions for a %s opportunity', (status, expected) => {
        expect(transitionsForStatus(status as OpportunityStatusEnumApi).map(({ transition }) => transition)).toEqual(
            expected
        )
    })

    it('swaps in the server row on transition success', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/dismiss/': () => [
                    200,
                    { ...openOpportunity, status: 'dismissed', updated_at: '2026-07-04T00:00:00Z' },
                ],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([openOpportunity])

        await expectLogic(logic, () => {
            logic.actions.transitionOpportunity('opp-1', 'dismiss')
        })
            .toDispatchActions(['opportunityTransitionStarted', 'opportunityTransitionSucceeded'])
            .toMatchValues({ transitionsInFlight: {} })
        expect(logic.values.opportunities[0].status).toEqual('dismissed')
        expect(logic.values.opportunities[0].updated_at).toEqual('2026-07-04T00:00:00Z')
    })

    it('keeps the status unchanged and toasts when a transition fails', async () => {
        const errorSpy = jest.spyOn(lemonToast, 'error')
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/reopen/': () => [
                    400,
                    {
                        type: 'validation_error',
                        code: 'invalid',
                        detail: 'This opportunity is open; it must be dismissed to become open.',
                        attr: null,
                    },
                ],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([openOpportunity])

        await expectLogic(logic, () => {
            logic.actions.transitionOpportunity('opp-1', 'reopen')
        })
            .toDispatchActions(['opportunityTransitionStarted', 'opportunityTransitionFailed'])
            .toMatchValues({ transitionsInFlight: {} })
        expect(logic.values.opportunities[0].status).toEqual('open')
        expect(errorSpy).toHaveBeenCalledWith('This opportunity is open; it must be dismissed to become open.')
    })

    it('ignores a second transition for the same row while one is in flight', async () => {
        let requests = 0
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/dismiss/': () => {
                    requests += 1
                    return [200, { ...openOpportunity, status: 'dismissed' }]
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([openOpportunity])

        await expectLogic(logic, () => {
            logic.actions.transitionOpportunity('opp-1', 'dismiss')
            logic.actions.transitionOpportunity('opp-1', 'dismiss')
        }).toFinishAllListeners()
        expect(requests).toEqual(1)
    })

    it('marks the opportunity acted, copies the proposal, then navigates to the new-experiment page', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/acted/': () => [
                    200,
                    { ...openOpportunity, proposed_experiment: proposedExperiment, status: 'acted' },
                ],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([{ ...openOpportunity, proposed_experiment: proposedExperiment }])

        await expectLogic(logic, () => {
            logic.actions.createExperimentFromOpportunity('opp-1')
        })
            .toDispatchActions(['opportunityTransitionStarted', 'opportunityTransitionSucceeded'])
            .toMatchValues({ transitionsInFlight: {} })

        // The acted transition landed before the navigation, so accountability re-scores it.
        expect(logic.values.opportunities[0].status).toEqual('acted')
        expect(copyToClipboard).toHaveBeenCalledWith(
            'Hypothesis: Moving the entry point above the fold lifts subscription creation\n' +
                'Feature flag key: subscription-entry-point\n' +
                'Target metric insight: abc123\n' +
                'Variants: Control keeps the sidebar entry; test adds a button above the insights list.',
            'experiment proposal'
        )
        // The router prefixes the current project, so assert the app path suffix.
        expect(router.values.location.pathname.endsWith(urls.experiment('new'))).toBe(true)
    })

    it('omits the target-metric line from the clipboard for a dropped (null) target metric', async () => {
        const proposal = { ...proposedExperiment, target_metric: null }
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/acted/': () => [
                    200,
                    { ...openOpportunity, proposed_experiment: proposal, status: 'acted' },
                ],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([{ ...openOpportunity, proposed_experiment: proposal }])

        await expectLogic(logic, () => {
            logic.actions.createExperimentFromOpportunity('opp-1')
        }).toFinishAllListeners()

        expect(copyToClipboard).toHaveBeenCalledWith(
            'Hypothesis: Moving the entry point above the fold lifts subscription creation\n' +
                'Feature flag key: subscription-entry-point\n' +
                'Variants: Control keeps the sidebar entry; test adds a button above the insights list.',
            'experiment proposal'
        )
    })

    it('warns but still navigates when the proposal copy fails', async () => {
        const warningSpy = jest.spyOn(lemonToast, 'warning')
        copyToClipboard.mockResolvedValueOnce(false)
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/acted/': () => [
                    200,
                    { ...openOpportunity, proposed_experiment: proposedExperiment, status: 'acted' },
                ],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([{ ...openOpportunity, proposed_experiment: proposedExperiment }])

        await expectLogic(logic, () => {
            logic.actions.createExperimentFromOpportunity('opp-1')
        }).toFinishAllListeners()

        expect(warningSpy).toHaveBeenCalledWith('Could not copy the proposal — find it on the opportunity row')
        // The proposal survives on the row, so a failed copy must not block the experiment flow.
        expect(router.values.location.pathname.endsWith(urls.experiment('new'))).toBe(true)
    })

    it('stays on the scene and keeps the row open when the acted transition fails', async () => {
        const errorSpy = jest.spyOn(lemonToast, 'error')
        const pathBefore = router.values.location.pathname
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/acted/': () => [
                    400,
                    { type: 'validation_error', code: 'invalid', detail: 'This opportunity is acted.', attr: null },
                ],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([{ ...openOpportunity, proposed_experiment: proposedExperiment }])

        await expectLogic(logic, () => {
            logic.actions.createExperimentFromOpportunity('opp-1')
        })
            .toDispatchActions(['opportunityTransitionStarted', 'opportunityTransitionFailed'])
            .toMatchValues({ transitionsInFlight: {} })

        expect(logic.values.opportunities[0].status).toEqual('open')
        expect(router.values.location.pathname).toEqual(pathBefore)
        expect(errorSpy).toHaveBeenCalledWith('This opportunity is acted.')
    })

    it('ignores a create-experiment click for a row without a proposal', async () => {
        let requests = 0
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/acted/': () => {
                    requests += 1
                    return [200, { ...openOpportunity, status: 'acted' }]
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([openOpportunity])

        await expectLogic(logic, () => {
            logic.actions.createExperimentFromOpportunity('opp-1')
        }).toFinishAllListeners()
        expect(requests).toEqual(0)
    })

    it('loads opportunities on first switch to the tab only', async () => {
        let requests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/pulse/opportunities/': () => {
                    requests += 1
                    return [200, { count: 1, results: [openOpportunity] }]
                },
            },
        })
        // Mounting the scene must not fetch the non-default tab.
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).toNotHaveDispatchedActions(['loadOpportunities'])

        await expectLogic(logic, () => {
            logic.actions.setActiveTab('opportunities')
        }).toFinishAllListeners()
        expect(requests).toEqual(1)
        expect(logic.values.opportunities).toHaveLength(1)

        await expectLogic(logic, () => {
            logic.actions.setActiveTab('briefs')
            logic.actions.setActiveTab('opportunities')
        }).toFinishAllListeners()
        expect(requests).toEqual(1) // subsequent switches reuse the loaded list
    })

    it('retries the opportunities load on the next switch after a failure', async () => {
        silenceKeaLoadersErrors()
        const errorSpy = jest.spyOn(lemonToast, 'error')
        let requests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/pulse/opportunities/': () => {
                    requests += 1
                    return requests === 1 ? [500, {}] : [200, { count: 1, results: [openOpportunity] }]
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setActiveTab('opportunities')
        }).toFinishAllListeners()
        expect(requests).toEqual(1)
        expect(errorSpy).toHaveBeenCalled()

        // A failed load must not latch the loaded flag and masquerade as an empty panel.
        await expectLogic(logic, () => {
            logic.actions.setActiveTab('briefs')
            logic.actions.setActiveTab('opportunities')
        }).toFinishAllListeners()
        expect(requests).toEqual(2)
        expect(logic.values.opportunities).toHaveLength(1)
        resumeKeaLoadersErrors()
    })

    it('records a helpfulness vote and swaps in the server row', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/feedback/': () => [
                    200,
                    { ...openOpportunity, my_vote: true, helpful_count: 1 },
                ],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([openOpportunity])

        await expectLogic(logic, () => {
            logic.actions.voteOnOpportunity('opp-1', true)
        })
            .toDispatchActions(['feedbackVoteStarted', 'opportunityFeedbackUpdated'])
            .toMatchValues({ feedbackVotesInFlight: {} })
        expect(logic.values.opportunities[0].my_vote).toBe(true)
        expect(logic.values.opportunities[0].helpful_count).toBe(1)
    })

    it('clears a brief vote by posting null and swaps the detail on confirmation', async () => {
        let captured: Record<string, unknown> | null = null
        const votedBrief = { ...readyBrief, my_vote: true, helpful_count: 1 }
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/briefs/:id/feedback/': async (info) => {
                    captured = (await info.request.json()) as Record<string, unknown>
                    return [200, { ...votedBrief, my_vote: null, helpful_count: 0 }]
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadBriefDetailSuccess(votedBrief as unknown as ProductBriefApi)

        await expectLogic(logic, () => {
            logic.actions.voteOnBrief('brief-1', null)
        })
            .toDispatchActions(['feedbackVoteStarted', 'briefFeedbackUpdated'])
            .toMatchValues({ feedbackVotesInFlight: {} })
        expect(captured).toEqual({ helpful: null })
        expect(logic.values.briefDetail?.my_vote).toBeNull()
        expect(logic.values.briefDetail?.helpful_count).toBe(0)
    })

    it('ignores a second vote for the same target while one is in flight', async () => {
        let requests = 0
        useMocks({
            post: {
                '/api/projects/:team_id/pulse/opportunities/:id/feedback/': () => {
                    requests += 1
                    return [200, { ...openOpportunity, my_vote: true, helpful_count: 1 }]
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([openOpportunity])

        await expectLogic(logic, () => {
            logic.actions.voteOnOpportunity('opp-1', true)
            logic.actions.voteOnOpportunity('opp-1', false)
        }).toFinishAllListeners()
        expect(requests).toEqual(1)
    })

    it('keeps the row unchanged, clears the guard, and toasts when a vote fails', async () => {
        const errorSpy = jest.spyOn(lemonToast, 'error')
        useMocks({
            post: { '/api/projects/:team_id/pulse/opportunities/:id/feedback/': () => [500, {}] },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOpportunitiesSuccess([openOpportunity])

        await expectLogic(logic, () => {
            logic.actions.voteOnOpportunity('opp-1', true)
        })
            .toDispatchActions(['feedbackVoteStarted', 'feedbackVoteFailed'])
            .toMatchValues({ feedbackVotesInFlight: {} })
        expect(logic.values.opportunities[0].my_vote).toBeNull()
        expect(errorSpy).toHaveBeenCalledWith('Saving your feedback failed')
    })

    it('reports product_brief_viewed once per brief', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')

        await expectLogic(logic, () => {
            logic.actions.loadBriefDetailSuccess(readyBrief as unknown as ProductBriefApi)
            logic.actions.loadBriefDetailSuccess(readyBrief as unknown as ProductBriefApi)
        }).toFinishAllListeners()

        const viewedCalls = captureSpy.mock.calls.filter(([event]) => event === 'product_brief_viewed')
        expect(viewedCalls).toHaveLength(1)
        expect(viewedCalls[0][1]).toMatchObject({ brief_id: 'brief-1', status: 'ready' })
    })

    it('does not report product_brief_viewed for a generating brief', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')

        await expectLogic(logic, () => {
            logic.actions.loadBriefDetailSuccess(generatingBrief as unknown as ProductBriefApi)
        }).toFinishAllListeners()

        expect(captureSpy.mock.calls.filter(([event]) => event === 'product_brief_viewed')).toHaveLength(0)
    })

    it('has no citation table entry for unknown types, which render unlinked', () => {
        expect(CITATION_TYPES['signal_report']).toBeUndefined()
    })
})
