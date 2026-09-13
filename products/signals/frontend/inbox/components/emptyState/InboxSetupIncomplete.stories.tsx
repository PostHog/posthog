import type { Meta, StoryObj } from '@storybook/react'

import { InboxSetupIncomplete } from './InboxSetupIncomplete'

// What the inbox shows once a setup run ends with nothing watching the project. Replaces the
// waiting state, which would otherwise promise work that can never arrive.
const meta: Meta<typeof InboxSetupIncomplete> = {
    title: 'Scenes-App/Inbox/Setup incomplete',
    component: InboxSetupIncomplete,
    parameters: { layout: 'fullscreen', viewMode: 'story' },
}
export default meta

export const SetupIncomplete: StoryObj<typeof InboxSetupIncomplete> = {}
