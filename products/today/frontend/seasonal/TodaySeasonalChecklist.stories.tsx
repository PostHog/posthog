import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { ToastProvider } from '@posthog/quill'

import type { SeasonalChecklistApi } from '../generated/api.schemas'
import { TodaySeasonalChecklist } from './TodaySeasonalChecklist'
import { todaySeasonalChecklistLogic } from './todaySeasonalChecklistLogic'

const checklist: SeasonalChecklistApi = {
    campaign: 'storybook-winter',
    title: 'Before you log off',
    description: 'Four things to set up so you hear about problems while you are away.',
    reason: 'Picked from the products you use most: Error tracking, Feature flags, LLM analytics',
    badge: 'Seasonal',
    bubble: '4 things before you log off',
    done_title: 'You’re all set',
    done_description: 'If something breaks while you are away, you will hear about it first.',
    accessories: ['xmas-hat', 'xmas-scarf'],
    snow: false,
    lights: true,
    items: [
        {
            key: 'alerts',
            title: 'Get alerted when a key metric drops',
            description: 'Add an alert to the metric you check most. It checks the metric every hour.',
            icon: 'bell',
            action: { kind: 'ask_ai', prompt: 'Add an alert to my most viewed insight.' },
            done: null,
        },
        {
            key: 'errors',
            title: 'Hear about new errors first',
            description: 'Send each new exception to Slack.',
            icon: 'bug',
            action: { kind: 'ask_ai', prompt: 'Send new exceptions to Slack.' },
            done: null,
        },
        {
            key: 'flags',
            title: 'Check flags that are mid-rollout',
            description: 'Pause partly rolled out flags or schedule the next step.',
            icon: 'toggle',
            action: { kind: 'ask_ai', prompt: 'List my partly rolled out flags.' },
            done: null,
        },
        {
            key: 'mcp',
            title: 'Ask PostHog from your phone',
            description: 'Connect the PostHog MCP to Claude or ChatGPT.',
            icon: 'plug',
            action: { kind: 'ask_ai', prompt: 'Help me connect the PostHog MCP.' },
            done: true,
        },
    ],
}

const meta = {
    title: 'Scenes-App/Today/Seasonal checklist',
    parameters: {
        layout: 'fullscreen',
        testOptions: { snapshotBrowsers: [] },
    },
    render: () => (
        <ToastProvider>
            <main className="h-screen overflow-auto">
                <div data-quill className="mx-auto h-full max-w-[720px]">
                    <TodaySeasonalChecklist checklist={checklist} />
                </div>
            </main>
        </ToastProvider>
    ),
} satisfies Meta

export default meta
type Story = StoryObj<{}>

export const HogOnThePage: Story = {}

function OpenChecklist(): JSX.Element {
    useEffect(() => {
        const logic = todaySeasonalChecklistLogic({ checklist })
        const unmount = logic.mount()
        logic.actions.openChecklist()
        return unmount
    }, [])
    return meta.render()
}

export const ChecklistOpen: Story = {
    render: () => <OpenChecklist />,
}
