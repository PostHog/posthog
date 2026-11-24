import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { QuillPrototypeExperimentPageV10, RUN_PROGRESS, SHELL_STATE } from './QuillPrototypeExperimentPageV10'

/** Scratch stories for the experiment detail prototype, round 10: product names. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentPageV10> = {
    title: 'Prototype/Experiment detail v10',
    component: QuillPrototypeExperimentPageV10,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentPageV10>

function clickSetting(attr: string): Story['play'] {
    return async ({ canvasElement }) => {
        await new Promise((resolve) => setTimeout(resolve, 1500))
        const target = [...canvasElement.querySelectorAll<HTMLElement>(`[data-attr="${attr}"]`)].find(
            (element) => element.offsetParent !== null
        )
        target?.click()
    }
}

export const SettingsCard: Story = {
    args: { status: PROTOTYPE_STATUS.running, shell: SHELL_STATE.sidebarClosed, progress: RUN_PROGRESS.targetReached },
}

export const SettingsCardSidebarOpen: Story = {
    args: { status: PROTOTYPE_STATUS.running, shell: SHELL_STATE.sidebarOpen, progress: RUN_PROGRESS.targetReached },
}

export const EditStatistics: Story = { ...SettingsCard, play: clickSetting('settings-statistics') }

export const ToggleCuped: Story = { ...SettingsCard, play: clickSetting('settings-cuped') }

export const EditRunningTimeTarget: Story = { ...SettingsCard, play: clickSetting('settings-running-time') }

export const CopyFlagKey: Story = { ...SettingsCard, play: clickSetting('settings-copy-flag') }

export const EditStatisticsSidebarOpen: Story = {
    ...SettingsCardSidebarOpen,
    play: clickSetting('settings-statistics'),
}

export const InProgress: Story = {
    args: { status: PROTOTYPE_STATUS.running, shell: SHELL_STATE.sidebarClosed, progress: RUN_PROGRESS.inProgress },
}

export const Scrolled: Story = {
    ...SettingsCard,
    play: async ({ canvasElement }) => {
        await new Promise((resolve) => setTimeout(resolve, 1500))
        canvasElement.querySelector<HTMLElement>('[data-attr="prototype-scroll"]')?.scrollTo({ top: 560 })
    },
}

export const MetricActionsMenu: Story = {
    args: { status: PROTOTYPE_STATUS.running, shell: SHELL_STATE.phone, progress: RUN_PROGRESS.targetReached },
    play: async ({ canvasElement }) => {
        await new Promise((resolve) => setTimeout(resolve, 1500))
        canvasElement.querySelector<HTMLElement>('[data-attr="prototype-scroll"]')?.scrollTo({ top: 1250 })
        await new Promise((resolve) => setTimeout(resolve, 300))
        const trigger = [...canvasElement.querySelectorAll<HTMLElement>('[aria-label="Metric actions"]')].find(
            (element) => element.offsetParent !== null
        )
        trigger?.click()
    },
}
