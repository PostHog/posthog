import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { METRIC_VIEW } from './PrototypeMetricViews'
import { QuillPrototypeExperimentPageV15, RUN_PROGRESS, SHELL_STATE } from './QuillPrototypeExperimentPageV15'

/** Scratch stories for prototype round 15, experiment detail: a switch for how metric results are drawn. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentPageV15> = {
    title: 'Prototype/v15/Experiment detail',
    component: QuillPrototypeExperimentPageV15,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentPageV15>

const RUNNING = {
    status: PROTOTYPE_STATUS.running,
    shell: SHELL_STATE.sidebarClosed,
    progress: RUN_PROGRESS.targetReached,
}

export const TargetReached: Story = { args: RUNNING }

export const InProgress: Story = { args: { ...RUNNING, progress: RUN_PROGRESS.inProgress } }

export const Draft: Story = { args: { ...RUNNING, status: PROTOTYPE_STATUS.draft } }

export const SidebarOpen: Story = { args: { ...RUNNING, shell: SHELL_STATE.sidebarOpen } }

export const OneChart: Story = { args: { ...RUNNING, metricView: METRIC_VIEW.oneChart } }

export const Candlestick: Story = { args: { ...RUNNING, metricView: METRIC_VIEW.candlestick } }

export const CandlestickSidebarOpen: Story = {
    args: { ...RUNNING, shell: SHELL_STATE.sidebarOpen, metricView: METRIC_VIEW.candlestick },
}

export const Matrix: Story = { args: { ...RUNNING, metricView: METRIC_VIEW.matrix } }

export const EffectMap: Story = { args: { ...RUNNING, metricView: METRIC_VIEW.effectMap } }

export const TwoCardsHidden: Story = { args: { ...RUNNING, hiddenPanels: ['health', 'hypothesis'] } }

export const AllCardsHidden: Story = {
    args: { ...RUNNING, hiddenPanels: ['exposures', 'health', 'hypothesis', 'settings'] },
}

export const Reordered: Story = { args: { ...RUNNING, panelOrder: ['settings', 'health', 'exposures', 'hypothesis'] } }
