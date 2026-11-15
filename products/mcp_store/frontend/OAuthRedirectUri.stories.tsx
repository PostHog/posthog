import type { Meta, StoryObj } from '@storybook/react'

import { OAuthRedirectUri } from './OAuthRedirectUri'

const meta: Meta<typeof OAuthRedirectUri> = {
    title: 'Scenes-App/MCP Store/OAuth redirect URI',
    component: OAuthRedirectUri,
    parameters: { layout: 'padded' },
}
export default meta

export const Default: StoryObj<typeof OAuthRedirectUri> = {}
