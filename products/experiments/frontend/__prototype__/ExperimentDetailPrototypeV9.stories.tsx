import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { QuillPrototypeExperimentPageV9, RUN_PROGRESS, SHELL_STATE } from './QuillPrototypeExperimentPageV9'

/** Scratch stories for the experiment detail prototype, round 9: CUPED named as in the product. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentPageV9> = {
    title: 'Prototype/Experiment detail v9',
    component: QuillPrototypeExperimentPageV9,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentPageV9>

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
