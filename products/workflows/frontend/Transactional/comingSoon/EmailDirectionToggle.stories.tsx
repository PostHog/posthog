import { Meta, StoryObj } from '@storybook/react'

import { userEvent } from 'storybook/test'

import { EmailDirectionToggle } from './EmailDirectionToggle'

const meta: Meta<typeof EmailDirectionToggle> = {
    title: 'Scenes-App/Transactional/Receiving coming soon',
    component: EmailDirectionToggle,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

export const NoteOpen: StoryObj<typeof EmailDirectionToggle> = {
    play: async ({ canvasElement }) => {
        await userEvent.click(
            canvasElement.querySelector('[data-attr="transactional-receiving-coming-soon"]') as HTMLElement
        )
    },
}
