import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { RESULT_CHART, RESULT_LAYOUT } from './PrototypeMetricViewsV16'
import { QuillPrototypeExperimentPageV21, RUN_PROGRESS, SHELL_STATE } from './QuillPrototypeExperimentPageV21'

/** Scratch stories for prototype round 21, experiment detail: a dense, centered results page. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentPageV21> = {
    title: 'Prototype/v21/Experiment detail',
    component: QuillPrototypeExperimentPageV21,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentPageV21>

const RUNNING = {
    status: PROTOTYPE_STATUS.running,
    shell: SHELL_STATE.sidebarClosed,
    progress: RUN_PROGRESS.targetReached,
}
const ONE_CHART = { resultLayout: RESULT_LAYOUT.allMetrics }

export const TargetReached: Story = { args: RUNNING }

export const InProgress: Story = { args: { ...RUNNING, progress: RUN_PROGRESS.inProgress } }

export const Draft: Story = { args: { ...RUNNING, status: PROTOTYPE_STATUS.draft } }

export const SidebarOpen: Story = { args: { ...RUNNING, shell: SHELL_STATE.sidebarOpen } }

export const CandlestickPerMetric: Story = { args: { ...RUNNING, resultChart: RESULT_CHART.candlestick } }

export const MatrixPerMetric: Story = { args: { ...RUNNING, resultChart: RESULT_CHART.matrix } }

export const TrendOneChart: Story = { args: { ...RUNNING, ...ONE_CHART } }

export const CandlestickOneChart: Story = { args: { ...RUNNING, ...ONE_CHART, resultChart: RESULT_CHART.candlestick } }

export const MatrixOneChart: Story = { args: { ...RUNNING, ...ONE_CHART, resultChart: RESULT_CHART.matrix } }
