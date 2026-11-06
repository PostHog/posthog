import { Meta, StoryObj } from '@storybook/react'

import { userEvent } from 'storybook/test'

import { SmtpComingSoonButton } from './SmtpComingSoonButton'

const meta: Meta<typeof SmtpComingSoonButton> = {
    title: 'Scenes-App/Transactional/SMTP coming soon',
    component: SmtpComingSoonButton,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

export const NoteOpen: StoryObj<typeof SmtpComingSoonButton> = {
    play: async ({ canvasElement }) => {
        await userEvent.click(
            canvasElement.querySelector('[data-attr="transactional-smtp-coming-soon"]') as HTMLElement
        )
    },
}
