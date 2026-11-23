import type { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { AiVisibilityEnginesSetting } from './AiVisibilityEnginesSetting'
import { EXAMPLE_ENGINE_SETTINGS } from './contentAutopilotStoryFixtures'

const meta: Meta<typeof AiVisibilityEnginesSetting> = {
    title: 'Products/Web Analytics/Content autopilot/Engines setting',
    component: AiVisibilityEnginesSetting,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/aeo_engines/': () => [200, EXAMPLE_ENGINE_SETTINGS],
            },
        }),
    ],
}

export default meta

export const Engines: StoryFn<typeof AiVisibilityEnginesSetting> = () => (
    <div className="p-4 max-w-200">
        <AiVisibilityEnginesSetting />
    </div>
)
