// PROTOTYPE, never merged: PostHog/michaelr-context#421. Saved views, tags and search inside the accepted Email &
// Messaging navigation (#419, shape A). Open a story, then flip variants with the bar at the bottom or the arrow keys.
import type { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'

import { messagingNavPrototypeLogic } from '~/layout/today/messagingNavPrototype/messagingNavPrototypeLogic'

import navMeta from './MessagingNav.prototype.stories'
import { ViewsVariant, setViewsVariant } from './views/viewsPrototypeStore'
import { ViewsPrototypeSwitcher } from './views/ViewsPrototypeSwitcher'

let appliedForStory: string | null = null

const meta: Meta = {
    component: App,
    title: 'Prototypes/Email & Messaging saved views',
    decorators: [
        // The navigation story's request mocks, so the app shell and the calendar load.
        (navMeta.decorators as any[])[0],
        (Story, { id, parameters }) => {
            // The navigation stays as accepted: shape A, the in-scene sidebar.
            messagingNavPrototypeLogic.mount()
            if (appliedForStory !== id) {
                appliedForStory = id
                messagingNavPrototypeLogic.actions.setVariant('A')
                setViewsVariant(parameters.viewsVariant as ViewsVariant, false)
            }
            return (
                <>
                    <Story />
                    <ViewsPrototypeSwitcher />
                </>
            )
        },
    ],
    parameters: navMeta.parameters,
}
export default meta

type Story = StoryObj

export const VariantA: Story = {
    parameters: { viewsVariant: 'A', pageUrl: '/messaging/broadcasts?views=A' },
}
export const VariantB: Story = {
    parameters: { viewsVariant: 'B', pageUrl: '/messaging/broadcasts?views=B' },
}
export const VariantC: Story = {
    parameters: { viewsVariant: 'C', pageUrl: '/messaging/broadcasts?views=C' },
}
export const VariantD: Story = {
    parameters: { viewsVariant: 'D', pageUrl: '/messaging/broadcasts?views=D' },
}
export const SavedViewAcrossTypes: Story = {
    parameters: { viewsVariant: 'A', pageUrl: '/messaging/view-onboarding?views=A' },
}
export const SearchAcrossTypes: Story = {
    parameters: { viewsVariant: 'A', pageUrl: '/messaging/search?q=welcome&views=A' },
}
