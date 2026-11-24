import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { RESULT_CHART, RESULT_LAYOUT } from './PrototypeMetricViewsV16'
import {
    type PanelKey,
    QuillPrototypeExperimentPageV18,
    RUN_PROGRESS,
    SHELL_STATE,
} from './QuillPrototypeExperimentPageV18'

/** Scratch stories for prototype round 19, experiment detail. The detail page has no change since v18. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentPageV18> = {
    title: 'Prototype/v19/Experiment detail',
    component: QuillPrototypeExperimentPageV18,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentPageV18>

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

export const CandlestickOneChartSidebarOpen: Story = {
    args: { ...RUNNING, ...ONE_CHART, shell: SHELL_STATE.sidebarOpen, resultChart: RESULT_CHART.candlestick },
}

export const MatrixOneChart: Story = { args: { ...RUNNING, ...ONE_CHART, resultChart: RESULT_CHART.matrix } }

export const TwoCardsHidden: Story = { args: { ...RUNNING, hiddenPanels: ['health', 'hypothesis'] } }

export const AllCardsHidden: Story = {
    args: { ...RUNNING, hiddenPanels: ['exposures', 'health', 'hypothesis', 'settings'] },
}

export const Reordered: Story = { args: { ...RUNNING, panelOrder: ['settings', 'health', 'exposures', 'hypothesis'] } }

export const TwoCardsCollapsed: Story = { args: { ...RUNNING, collapsedPanels: ['exposures', 'hypothesis'] } }

export const AllCardsCollapsed: Story = {
    args: { ...RUNNING, collapsedPanels: ['exposures', 'health', 'hypothesis', 'settings'] },
}

export const AllCardsCollapsedSidebarOpen: Story = {
    args: {
        ...RUNNING,
        shell: SHELL_STATE.sidebarOpen,
        collapsedPanels: ['exposures', 'health', 'hypothesis', 'settings'],
    },
}

export const DraftCardsCollapsed: Story = {
    args: { ...RUNNING, status: PROTOTYPE_STATUS.draft, collapsedPanels: ['exposures', 'hypothesis', 'settings'] },
}

const ONLY_EXPOSURES = { hiddenPanels: ['health', 'hypothesis', 'settings'] as PanelKey[] }

export const OnlyExposures: Story = { args: { ...RUNNING, ...ONLY_EXPOSURES } }

export const OnlyExposuresSidebarOpen: Story = {
    args: { ...RUNNING, ...ONLY_EXPOSURES, shell: SHELL_STATE.sidebarOpen },
}
