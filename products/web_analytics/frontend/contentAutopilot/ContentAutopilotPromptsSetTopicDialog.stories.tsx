import type { Meta, StoryFn } from '@storybook/react'
import { waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { userEvent } from 'storybook/test'

import { ContentAutopilotPrompts } from './ContentAutopilotPrompts'
import {
    EXAMPLE_ENGINE_SETTINGS,
    EXAMPLE_PROMPT_TOPICS,
    EXAMPLE_PROMPTS,
    EXAMPLE_SETUP_CONTEXT,
} from './contentAutopilotStoryFixtures'

const meta: Meta<typeof ContentAutopilotPrompts> = {
    title: 'Products/Web Analytics/Content autopilot/Set topic',
    component: ContentAutopilotPrompts,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
        // The fixtures carry fixed dates and the list shows them relative to now, so the clock is pinned near them.
        mockDate: '2026-09-30',
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/aeo_prompts/': () => [
                    200,
                    { count: EXAMPLE_PROMPTS.length, next: null, previous: null, results: EXAMPLE_PROMPTS },
                ],
                '/api/projects/:team_id/aeo_prompts/topics/': () => [200, EXAMPLE_PROMPT_TOPICS],
                '/api/projects/:team_id/aeo_engines/': () => [200, EXAMPLE_ENGINE_SETTINGS],
                '/api/projects/:team_id/aeo_setup/context/': () => [200, EXAMPLE_SETUP_CONTEXT],
            },
        }),
    ],
}

export default meta

const element = (selector: string): Promise<HTMLElement> =>
    waitFor(
        () => {
            const found = document.querySelector<HTMLElement>(selector)
            if (!found) {
                throw new Error(`${selector} is not rendered`)
            }
            return found
        },
        { timeout: 15000 }
    )

export const PickPromptsAndSetTopic: StoryFn<typeof ContentAutopilotPrompts> = () => (
    <div className="p-6">
        <ContentAutopilotPrompts />
    </div>
)
PickPromptsAndSetTopic.play = async () => {
    await element('[data-attr=content-autopilot-prompt-select]')
    const rows = document.querySelectorAll<HTMLElement>('[data-attr=content-autopilot-prompt-select]')
    await userEvent.click(rows[0])
    await userEvent.click(rows[1])
    await userEvent.click(await element('[data-attr=content-autopilot-prompts-set-topic]'))
    await userEvent.type(await element('[data-attr=content-autopilot-prompts-set-topic-input]'), 'Se')
}
