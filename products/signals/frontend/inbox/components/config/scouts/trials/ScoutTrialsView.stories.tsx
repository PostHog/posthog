import type { Meta, StoryObj } from '@storybook/react'

import { trialFixtureConfig, trialFixtureResult, trialFixtureSetup } from './scoutTrialsFixtures'
import { ScoutTrialsView, ScoutTrialsViewProps } from './ScoutTrialsView'
import { createTrialBatch, initialTrialVariants } from './scoutTrialUtils'

const noop = (): void => {}
const variants = initialTrialVariants(trialFixtureSetup)
const defaults: ScoutTrialsViewProps = {
    configs: [trialFixtureConfig],
    configsLoading: false,
    setup: trialFixtureSetup,
    setupLoading: false,
    history: { results: [], has_more: false },
    historyLoading: false,
    selectedConfigId: trialFixtureConfig.id,
    variants,
    repeats: 1,
    note: '',
    batch: null,
    tracked: [],
    results: {},
    resultErrors: {},
    submitting: false,
    refreshing: false,
    canceling: [],
    pageError: null,
    pollError: null,
    selectedLaunchId: null,
    rows: [],
    selectedResult: null,
    formError: null,
    totalRuns: 2,
    hasUnaccepted: false,
    loadConfigs: noop,
    loadSetup: noop,
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
    title: 'Scenes-App/Inbox/Scout comparisons',
    component: ScoutTrialsView,
    args: defaults,
    parameters: { layout: 'fullscreen', testOptions: { waitForLoadersToDisappear: false } },
}
export default meta
type Story = StoryObj<typeof ScoutTrialsView>

export const Idle: Story = {}
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
            blocked_reason: 'Comparisons are disabled until private capture is enabled on the gateway.',
        },
    },
}
export const Loading: Story = { args: { configs: null, configsLoading: true, selectedConfigId: null, setup: null } }
export const Error: Story = {
    args: { setup: null, pageError: "Couldn't load this scout's comparison settings. Try again." },
}

const completedBatch = createTrialBatch(trialFixtureConfig.id, variants, 1, '', () => trialFixtureResult.launch_id)
completedBatch.submissions = completedBatch.submissions.map((entry) => ({ ...entry, accepted: true }))

export const Running: Story = {
    args: {
        batch: completedBatch,
        rows: variants.map((variant, index) => ({
            launchId: `running-${index}`,
            variant: variant.label,
            model: variant.model,
            effort: variant.effort,
            status: 'running',
            startedAt: trialFixtureResult.started_at,
            error: null,
            result: {
                ...trialFixtureResult,
                status: 'running',
                task_status: 'running',
                summary: '',
                reports: [],
                memory: {},
                completed_at: null,
            },
        })),
    },
}

export const Results: Story = {
    args: {
        batch: completedBatch,
        rows: [
            {
                launchId: trialFixtureResult.launch_id,
                variant: 'Baseline (1)',
                model: trialFixtureResult.model,
                effort: trialFixtureResult.reasoning_effort,
                status: 'completed',
                startedAt: trialFixtureResult.started_at,
                error: null,
                result: trialFixtureResult,
            },
        ],
    },
}
export const ResultDetails: Story = { args: { ...Results.args, selectedResult: trialFixtureResult } }
export const ResultsNarrow: Story = { ...Results, decorators: Narrow.decorators }
