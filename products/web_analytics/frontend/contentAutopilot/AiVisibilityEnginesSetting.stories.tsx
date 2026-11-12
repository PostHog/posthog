import type { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { AEOEngineSettingApi } from '../generated/api.schemas'
import { AiVisibilityEnginesSetting } from './AiVisibilityEnginesSetting'

const ENGINES: AEOEngineSettingApi[] = [
    { engine: 'claude-web-search', mode: 'web_search', available: true, enabled: true, frequency: 'daily' },
    { engine: 'openai-web-search', mode: 'web_search', available: true, enabled: true, frequency: 'daily' },
    { engine: 'perplexity-web-search', mode: 'web_search', available: false, enabled: true, frequency: 'daily' },
    { engine: 'exa-answer', mode: 'web_search', available: true, enabled: false, frequency: 'daily' },
    { engine: 'claude-no-search', mode: 'no_search', available: true, enabled: true, frequency: 'weekly' },
    { engine: 'openai-no-search', mode: 'no_search', available: true, enabled: false, frequency: 'daily' },
]

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
                '/api/projects/:team_id/aeo_engines/': () => [200, ENGINES],
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
