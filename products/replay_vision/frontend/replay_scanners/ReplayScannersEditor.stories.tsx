import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { RecordingsQuery } from '~/queries/schema/schema-general'

import { expect } from 'storybook/test'

import { replayScannersStoryConfig } from '../__mocks__/replayScannersStoryConfig'
import {
    estimate,
    experimentScanner,
    freeCreditsUsedQuota,
    freeOnlyScanner,
    quota,
    summarizerScanner,
    variantsDecorator,
    variantsReadout,
} from '../__mocks__/replayScannersStoryFixtures'
import type { DraftScannerResponseApi, VisionQuotaApi } from '../generated/api.schemas'
import { replayScannerLogic } from './replayScannerLogic'
import type { ScannerConfig, ScannerType } from './types'

const meta: Meta = {
    ...replayScannersStoryConfig,
    component: App,
    title: 'Scenes-App/Replay Vision',
}
export default meta

export const ScannerEditorDetails: StoryObj = {
    parameters: { pageUrl: urls.replayVisionScannerDetails(summarizerScanner.id) },
}

export const ScannerEditorConfigure: StoryObj = {
    parameters: { pageUrl: urls.replayVisionScannerConfigure(summarizerScanner.id) },
}

export const ScannerEditorTriggers: StoryObj = {
    parameters: { pageUrl: urls.replayVisionScannerTriggers(summarizerScanner.id) },
}

// The experiment shows as the first condition of the filters, so a scanner with no filters of its own
// does not read as scanning every recording.
export const ScannerEditorTriggersExperiment: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerTriggers(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [variantsDecorator(variantsReadout())],
}

export const ScannerEditorBudget: StoryObj = {
    parameters: { pageUrl: urls.replayVisionScannerBudget(summarizerScanner.id) },
}

// The recordings-first experiment arm only applies while creating, so this story starts a new scanner.
export const ScannerEditorTriggersRecordingsFirst: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerTriggers('new'),
        featureFlags: { [FEATURE_FLAGS.VISION_SCANNER_WIZARD_RECORDINGS_FIRST]: 'test' },
    },
}

// The goal step: one goal box with starters that fill it, a budget, and a single draft button.
export const ScannerEditorGoalFlow: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerGoal('new'),
    },
}

const goalDraft: DraftScannerResponseApi = {
    name: 'Billing give-up monitor',
    description: 'Flags sessions where a user reaches billing and leaves without finishing.',
    scanner_type: 'monitor',
    scanner_config: {
        prompt: 'Did the user reach a billing page and leave without completing what they started there? Answer yes or no with a one-sentence reason.',
        allow_inconclusive: true,
    },
    rationale:
        'You want to catch people who give up around billing, so this watches sessions that touch your billing pages and asks a yes/no question about each one. Giving up looks unremarkable, so it watches all matching replays rather than only the eventful ones.',
    query: {
        kind: 'RecordingsQuery',
        properties: [
            {
                type: 'recording',
                key: 'visited_page',
                value: ['/organization/billing/overview', '/organization/billing/plans', '/checkout'],
                operator: 'icontains',
            },
        ],
    },
    query_additions: null,
    sampling_rate: 0.25,
    model: 'gemini-3-flash-preview',
    credit_limit: 5000,
    free_only: false,
    estimated_monthly_observations: 1000,
}

// The landing step after a goal draft: the whole config ordered by comprehension, each section
// deep-linking into the wizard step that edits it. Seeded through the same action the loader fires.
const seedGoalOverviewDraft: Decorator = (StoryFn) => {
    const logic = replayScannerLogic({ id: 'new' })
    logic.mount()
    // The success listener's stale-navigation guard sees the overview URL and skips its own
    // reset + redirect, so only the goalDraft reducer applies; the form is seeded by hand.
    logic.actions.draftScannerFromGoalSuccess(goalDraft)
    logic.actions.setScannerValues({
        name: goalDraft.name,
        description: goalDraft.description,
        scanner_type: goalDraft.scanner_type as ScannerType,
        scanner_config: goalDraft.scanner_config as ScannerConfig,
        query: goalDraft.query as RecordingsQuery,
        sampling_rate: goalDraft.sampling_rate ?? 1,
    })
    return <StoryFn />
}

export const ScannerEditorGoalOverview: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerOverview('new'),
    },
    decorators: [seedGoalOverviewDraft],
}

// The recordings-first experiment arm reviews the eligible recordings before the prompt.
export const ScannerEditorGoalOverviewRecordingsFirst: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerOverview('new'),
        featureFlags: { [FEATURE_FLAGS.VISION_SCANNER_WIZARD_RECORDINGS_FIRST]: 'test' },
    },
    decorators: [seedGoalOverviewDraft],
}

const addedBillingEvent = { id: 'billing_limit_set', name: 'billing_limit_set', type: 'events', order: 0 }

const goalDraftFromReplayFilters: DraftScannerResponseApi = {
    ...goalDraft,
    query: {
        kind: 'RecordingsQuery',
        properties: [{ type: 'recording', key: 'visited_page', value: ['/checkout'], operator: 'icontains' }],
        events: [addedBillingEvent],
    },
    query_additions: { kind: 'RecordingsQuery', events: [addedBillingEvent] },
}

export const ScannerEditorGoalOverviewFromReplayFilters: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerOverview('new'),
    },
    decorators: [
        (StoryFn) => {
            const logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            logic.actions.draftScannerFromGoalSuccess(goalDraftFromReplayFilters)
            logic.actions.setScannerValues({
                name: goalDraftFromReplayFilters.name,
                description: goalDraftFromReplayFilters.description,
                scanner_type: goalDraftFromReplayFilters.scanner_type as ScannerType,
                scanner_config: goalDraftFromReplayFilters.scanner_config as ScannerConfig,
                query: goalDraftFromReplayFilters.query as RecordingsQuery,
                sampling_rate: goalDraftFromReplayFilters.sampling_rate ?? 1,
            })
            return <StoryFn />
        },
    ],
}

// The same landing step for a goal that named an experiment: the eligible-recordings section
// leads with the experiment and variant the scan watches, which no page filter can express.
export const ScannerEditorGoalOverviewExperiment: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerOverview('new'),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [
        mswDecorator({
            get: {
                // The targeting card and the snack read the experiment's name from this fetch.
                '/api/projects/:team_id/experiments/:id/': {
                    id: 11,
                    name: 'AI-based scanner creation',
                    description: 'Does the goal flow beat the template gallery?',
                    feature_flag_key: 'ai-scanner-creation-flow',
                    feature_flag: {
                        id: 11,
                        key: 'ai-scanner-creation-flow',
                        filters: {
                            multivariate: {
                                variants: [
                                    { key: 'control', rollout_percentage: 50 },
                                    { key: 'test', rollout_percentage: 50 },
                                ],
                            },
                        },
                    },
                    start_date: '2026-09-01T00:00:00Z',
                    end_date: null,
                    exposure_criteria: {},
                },
            },
        }),
        (StoryFn) => {
            const logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            const draft: DraftScannerResponseApi = {
                ...goalDraft,
                name: 'New creation flow friction',
                description: 'Describes how participants get through the new AI creation flow.',
                scanner_type: 'experiment',
                scanner_config: {
                    prompt: 'Watch the scanner creation flow. Note where the participant hesitates, backtracks, or gives up while describing their goal, and how the session ends.',
                    length: 'medium',
                    experiment_id: 11,
                    variants: ['test'],
                    balance_variants: true,
                },
                rationale:
                    'Your goal is about the new AI creation flow, so this watches only the sessions of people the experiment put in its test variant, on the pages where that flow lives. Struggling looks unremarkable, so it watches all matching replays rather than only the eventful ones.',
                query: {
                    kind: 'RecordingsQuery',
                    properties: [
                        {
                            type: 'recording',
                            key: 'visited_page',
                            value: ['/replay-vision/scanners/new'],
                            operator: 'icontains',
                        },
                    ],
                    events: [
                        {
                            id: 'replay_vision_scanner_creation_started',
                            name: 'replay_vision_scanner_creation_started',
                            type: 'events',
                            order: 0,
                        },
                    ],
                } as RecordingsQuery,
            }
            logic.actions.draftScannerFromGoalSuccess(draft)
            logic.actions.setScannerValues({
                name: draft.name,
                description: draft.description,
                scanner_type: draft.scanner_type as ScannerType,
                scanner_config: draft.scanner_config as ScannerConfig,
                query: draft.query as RecordingsQuery,
                sampling_rate: draft.sampling_rate ?? 1,
            })
            return <StoryFn />
        },
    ],
}

// A filter with many values renders as one long snack, which must wrap inside the card rather than
// push it past the edge of the page.
export const ScannerEditorGoalOverviewLongFilters: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerOverview('new'),
    },
    decorators: [
        (StoryFn) => {
            const logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            const draft: DraftScannerResponseApi = {
                ...goalDraft,
                name: 'Sign-in friction monitor',
                description: 'Flags sessions where a user struggles to sign in.',
                query: {
                    kind: 'RecordingsQuery',
                    properties: [
                        {
                            type: 'event',
                            key: '$screen_name',
                            value: [
                                '/sign-in',
                                '/sign-in/verify-code',
                                '/sign-in/magic-link',
                                '/account/security',
                                '/account/two-factor-setup',
                                '/password/forgot',
                                '/password/reset',
                                '/sign-up/more-details',
                            ],
                            operator: 'exact',
                        },
                    ],
                    events: [{ id: 'user_signed_in', name: 'user_signed_in', type: 'events', order: 0 }],
                } as RecordingsQuery,
            }
            logic.actions.draftScannerFromGoalSuccess(draft)
            logic.actions.setScannerValues({
                name: draft.name,
                description: draft.description,
                scanner_type: draft.scanner_type as ScannerType,
                scanner_config: draft.scanner_config as ScannerConfig,
                query: draft.query as RecordingsQuery,
                sampling_rate: draft.sampling_rate ?? 1,
            })
            return <StoryFn />
        },
    ],
}

// The overview while the draft is still generating: the loading bar and skeleton the user sees
// right after submitting the two questions.
export const ScannerEditorGoalOverviewLoading: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerOverview('new'),
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: '.LemonSkeleton' },
    },
    decorators: [
        // A draft request that never answers, because a failed one sends the page back to the goal step.
        mswDecorator({
            post: {
                '/api/projects/:team_id/vision/scanners/draft/': (): Promise<never> => new Promise(() => {}),
            },
        }),
        (StoryFn) => {
            const logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            // Hold the draft loader open so the overview renders its skeleton instead of a result.
            logic.actions.draftScannerFromGoal({
                goal: 'find out where people give up in billing',
                spend: { monthlyCreditBudget: 5000 },
            })
            return <StoryFn />
        },
    ],
}

// Free-only scanners stop when the org's free credits run out, so these quotas sit on either side of that.
const freeCreditsLeftQuota: VisionQuotaApi = { ...quota, credits_used: 600, credits_settled: 600, remaining: 9400 }

// Large enough that the free credits left, not the estimate, bound the forecast.
const largeEstimate = { ...estimate, estimated_observations_per_month: 3000, estimated_credits_per_month: 3000 }

// The headroom is the free credits left as a monthly rate over the 20 days to June 1.
const freeOnlyEditorDecorator = (
    quotaResponse: VisionQuotaApi,
    freeHeadroom: number
): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/projects/:team_id/vision/scanners/:id/': freeOnlyScanner,
            '/api/projects/:team_id/vision/quota/': quotaResponse,
        },
        post: {
            '/api/projects/:team_id/vision/scanners/estimate/': {
                ...largeEstimate,
                free_only_monthly_credits_left: freeHeadroom,
            },
        },
    })

// Plenty of free credits left: the forecast still caps this scanner at what they cover.
export const ScannerEditorBudgetFreeOnly: StoryObj = {
    parameters: { pageUrl: urls.replayVisionScannerBudget(freeOnlyScanner.id) },
    decorators: [freeOnlyEditorDecorator(freeCreditsLeftQuota, 2850)],
}

// 100 free credits left: the forecast shrinks to what they cover instead of warning about the org limit.
export const ScannerEditorBudgetFreeOnlyNearlyUsed: StoryObj = {
    parameters: { pageUrl: urls.replayVisionScannerBudget(freeOnlyScanner.id) },
    decorators: [freeOnlyEditorDecorator(quota, 150)],
}

// The goal flow with "Set a budget" picked instead of the free default.
export const ScannerEditorGoalFlowBudget: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerGoal('new'),
    },
    decorators: [
        (StoryFn) => {
            const logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            logic.actions.setGoalSpendMode('budget')
            return <StoryFn />
        },
    ],
}

// An experiment picked from the "Track an experiment" chip: the pick fills the goal box, links the experiment
// to the draft, and the chip shows its name.
export const ScannerEditorGoalFlowExperimentPicker: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerGoal('new'),
    },
    play: async ({ canvasElement }) => {
        const chip = await waitFor(() => {
            const button = canvasElement.querySelector('[data-attr="vision-goal-starter-experiment"]')
            expect(button).not.toHaveClass('LemonButton--loading')
            return button as HTMLElement
        })
        await userEvent.click(chip)
        await userEvent.click(await within(document.body).findByText('AI creation flow'))
    },
}

// No free credits left this period, so "Free" is disabled and the budget input shows.
export const ScannerEditorGoalFlowFreeCreditsUsed: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerGoal('new'),
    },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/vision/quota/': freeCreditsUsedQuota } })],
}

// A free draft whose estimate is more than the monthly free credits cover.
export const ScannerEditorGoalOverviewFreeOnly: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerOverview('new'),
    },
    decorators: [
        mswDecorator({ post: { '/api/projects/:team_id/vision/scanners/estimate/': largeEstimate } }),
        (StoryFn) => {
            const logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            logic.actions.draftScannerFromGoalSuccess(goalDraft)
            logic.actions.setScannerValues({
                name: goalDraft.name,
                description: goalDraft.description,
                scanner_type: goalDraft.scanner_type as ScannerType,
                scanner_config: goalDraft.scanner_config as ScannerConfig,
                query: goalDraft.query as RecordingsQuery,
                sampling_rate: 0.0001,
                free_only: true,
                credit_limit: null,
            })
            return <StoryFn />
        },
    ],
}
