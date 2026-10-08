import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { scoutRubricReferenceFixture } from '../scoutRubricFixtures'
import {
    trialFixtureComparison,
    trialFixtureConfig,
    trialFixtureEvaluation,
    trialFixtureEvaluationWithJudgeError,
    trialFixtureLongReport,
    trialFixtureResult,
    trialFixtureServerComparison,
    trialFixtureSetup,
} from './scoutTrialsFixtures'
import { ScoutTrialsView, ScoutTrialsViewProps } from './ScoutTrialsView'
import { initialTrialVariants } from './scoutTrialUtils'

const noop = (): void => {}
const variants = initialTrialVariants(trialFixtureSetup)
variants[1] = {
    ...variants[1],
    label: 'Candidate prompt',
    replacePrompt: true,
    prompt: 'Investigate checkout failures over the last 7 days. Cite captured query results and propose one next step.',
}
const defaults: ScoutTrialsViewProps = {
    featureFlags: { [FEATURE_FLAGS.SCOUT_TRIALS]: true },
    trialsDisabledReason: null,
    comparisonStates: {},
    comparisonState: { value: null, loading: false, resuming: false, error: null, notStarted: false },
    comparisonHistory: { results: [], has_more: false },
    comparisonHistoryLoading: false,
    comparisonRows: [],
    managedComparison: false,
    serverComparisonIds: [],
    trialView: 'setup',
    teamId: 2,
    fixedConfigId: trialFixtureConfig.id,
    showTrialList: noop,
    loadComparison: noop,
    resumeComparison: noop,
    loadComparisonHistory: noop,
    comparisons: [],
    comparisonsForConfig: [],
    selectedComparisonIds: {},
    selectedComparison: null,
    evaluations: {},
    evaluationState: { value: null, loading: false, scoring: false, error: null, notStarted: false },
    scoreDisabledReason: 'Start or select a comparison first.',
    selectComparison: noop,
    loadEvaluation: noop,
    scoreComparison: noop,
    newScoringAttempt: noop,
    downloadEvaluation: noop,
    configs: [trialFixtureConfig],
    configsLoading: false,
    setup: trialFixtureSetup,
    setupLoading: false,
    history: { results: [], has_more: false },
    historyLoading: false,
    selectedConfigId: trialFixtureConfig.id,
    variants,
    repeats: 2,
    note: '',
    batch: null,
    tracked: [],
    results: {},
    resultErrors: {},
    submitting: false,
    refreshing: false,
    canceling: [],
    cancelErrors: {},
    pageError: null,
    pollError: null,
    formPageError: null,
    resultPollError: null,
    loadErrors: { configs: null, setup: null, history: null, comparisonHistory: null },
    selectedLaunchId: null,
    rows: [],
    selectedResult: null,
    formError: null,
    totalRuns: 4,
    hasUnaccepted: false,
    loadConfigs: noop,
    loadSetup: noop,
    retryPageLoad: noop,
    loadHistory: noop,
    selectConfig: noop,
    updateVariant: noop,
    addVariant: noop,
    removeVariant: noop,
    setRepeats: noop,
    setNote: noop,
    submitComparison: noop,
    newComparison: noop,
    refreshResults: noop,
    selectResult: noop,
    downloadResults: noop,
    cancelRun: noop,
}

const meta: Meta<typeof ScoutTrialsView> = {
    title: 'Scenes-App/Inbox/Scout trials',
    id: 'scenes-app-inbox-scout-comparisons',
    component: ScoutTrialsView,
    args: defaults,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/signals/scout/rubrics/:config/': () => [
                    200,
                    {
                        config_id: trialFixtureConfig.id,
                        skill_name: trialFixtureSetup.skill_name,
                        revision: 2,
                        criteria: trialFixtureLongReport.criteria.map((criterion) => ({
                            ...criterion,
                            enabled: true,
                            source: 'custom',
                        })),
                        generation: null,
                        reference_context: scoutRubricReferenceFixture,
                        reference_generation_id: '00000000-0000-4000-8000-000000000032',
                    },
                ],
            },
        }),
    ],
    parameters: { layout: 'fullscreen', testOptions: { waitForLoadersToDisappear: false } },
}
export default meta
type Story = StoryObj<typeof ScoutTrialsView>

export const Idle: Story = { args: { trialView: 'list' } }
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px] max-w-full">
                <Story />
            </div>
        ),
    ],
}
export const Wide: Story = {
    decorators: [
        (Story) => (
            <div className="w-[1000px] max-w-full">
                <Story />
            </div>
        ),
    ],
}
export const Disabled: Story = {
    args: {
        setup: {
            ...trialFixtureSetup,
            ready: false,
            blocked_reason: 'Trials are disabled until private capture is enabled on the gateway.',
        },
    },
}
export const Loading: Story = { args: { configs: null, configsLoading: true, selectedConfigId: null, setup: null } }
export const Error: Story = {
    args: { setup: null, pageError: "Couldn't load this scout's trial settings. Try again." },
}

const runningRows = trialFixtureComparison.groups.flatMap((group, variantIndex) =>
    group.launchIds.map((launchId, repeatIndex) => ({
        launchId,
        variant: `${variantIndex === 0 ? 'Baseline' : 'Candidate prompt'} · run ${repeatIndex + 1}`,
        model: trialFixtureResult.model,
        effort: trialFixtureResult.reasoning_effort,
        status: variantIndex === 0 && repeatIndex === 0 ? 'completed' : 'running',
        startedAt: trialFixtureResult.started_at,
        error: null,
        result: {
            ...trialFixtureResult,
            launch_id: launchId,
            status: variantIndex === 0 && repeatIndex === 0 ? 'completed' : 'running',
            task_status: variantIndex === 0 && repeatIndex === 0 ? 'completed' : 'in_progress',
            summary: '',
            reports: [],
            memory: {},
            completed_at: null,
        },
    }))
)
const completedRows = runningRows.map((row) => ({
    ...row,
    status: 'completed',
    result: {
        ...row.result,
        status: 'completed',
        task_status: 'completed',
        completed_at: trialFixtureResult.completed_at,
    },
}))

export const Running: Story = {
    args: {
        trialView: 'detail',
        comparisons: [trialFixtureComparison],
        comparisonsForConfig: [trialFixtureComparison],
        selectedComparison: trialFixtureComparison,
        managedComparison: true,
        serverComparisonIds: [trialFixtureComparison.id],
        comparisonStates: {
            [trialFixtureComparison.id]: {
                value: { ...trialFixtureServerComparison, status: 'running', evaluation: null },
                loading: false,
                resuming: false,
                error: null,
                notStarted: false,
            },
        },
        comparisonState: {
            value: { ...trialFixtureServerComparison, status: 'running', evaluation: null },
            loading: false,
            resuming: false,
            error: null,
            notStarted: false,
        },
        rows: runningRows,
        comparisonRows: runningRows,
    },
}
export const RunningNarrow: Story = { ...Running, decorators: Narrow.decorators }

export const Scored: Story = {
    args: {
        ...Running.args,
        rows: completedRows,
        comparisonRows: completedRows,
        comparisonState: { ...Running.args!.comparisonState!, value: trialFixtureServerComparison },
        comparisonStates: {
            [trialFixtureComparison.id]: { ...Running.args!.comparisonState!, value: trialFixtureServerComparison },
        },
        comparisons: [trialFixtureComparison],
        comparisonsForConfig: [trialFixtureComparison],
        selectedComparison: trialFixtureComparison,
        evaluationState: {
            value: trialFixtureServerComparison.evaluation,
            loading: false,
            scoring: false,
            error: null,
            notStarted: false,
        },
        scoreDisabledReason: 'This comparison has already been scored.',
    },
}
export const ScoredNarrow: Story = { ...Scored, decorators: Narrow.decorators }
export const ManyRubrics: Story = {
    args: {
        ...Scored.args,
        evaluationState: {
            ...Scored.args!.evaluationState!,
            value: {
                ...trialFixtureServerComparison.evaluation!,
                report: { ...trialFixtureLongReport, rubric_source: 'saved' },
            },
        },
    },
}
export const ManyRubricsNarrow: Story = { ...ManyRubrics, decorators: Narrow.decorators }
export const ScoredWithJudgeError: Story = {
    args: {
        ...Scored.args,
        evaluationState: {
            value: trialFixtureEvaluationWithJudgeError,
            loading: false,
            scoring: false,
            error: null,
            notStarted: false,
        },
    },
}
export const Scoring: Story = {
    args: {
        ...Scored.args,
        comparisonState: {
            ...Running.args!.comparisonState!,
            value: { ...trialFixtureServerComparison, status: 'judging' },
        },
        comparisonRows: completedRows,
        evaluationState: {
            value: { ...trialFixtureEvaluation, status: 'running', report: null },
            loading: false,
            scoring: false,
            error: null,
            notStarted: false,
        },
        scoreDisabledReason: 'This comparison is being scored.',
    },
}
export const ScoringNarrow: Story = { ...Scoring, decorators: Narrow.decorators }
export const ScoringUnavailable: Story = {
    args: {
        ...Scored.args,
        comparisonState: {
            ...Running.args!.comparisonState!,
            value: { ...trialFixtureServerComparison, status: 'unknown' },
        },
        evaluationState: {
            value: { ...trialFixtureEvaluation, status: 'unknown', report: null },
            loading: false,
            scoring: false,
            error: null,
            notStarted: false,
        },
        scoreDisabledReason: 'Refresh scoring status before starting an evaluation.',
    },
}

export const MissingSavedRubric: Story = {
    args: {
        ...Scored.args,
        comparisonState: {
            value: null,
            loading: false,
            resuming: false,
            notStarted: true,
            error: 'Generate suggestions, adopt their reference, and save the rubric before starting.',
        },
        evaluationState: {
            value: null,
            loading: false,
            scoring: false,
            error: 'Generate suggestions, adopt their reference, and save the rubric before scoring.',
            notStarted: true,
        },
        scoreDisabledReason: null,
    },
}

export const History: Story = { args: { ...Scored.args, trialView: 'list' } }
export const HistoryNarrow: Story = { ...History, decorators: Narrow.decorators }
