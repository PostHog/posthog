import type { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { AEOSetupContextApi, AEOSetupJobApi } from '../generated/api.schemas'
import { ContentAutopilotFirstRunCard } from './ContentAutopilotFirstRunCard'
import { ContentAutopilotSetupCard } from './ContentAutopilotSetupCard'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

const CONTEXT: AEOSetupContextApi = {
    websites: [
        { domain: 'hedgebox.net', source: 'pageviews', pageviews: 48210 },
        { domain: 'hedgebox-docs.net', source: 'pageviews', pageviews: 3120 },
    ],
    own_domains: [],
    active_prompts: 0,
    keywords: 0,
    has_checks: false,
    ai_data_processing_approved: true,
    first_run_available: true,
    prompt_target: 20,
    engines: [
        { engine: 'claude-web-search', mode: 'web_search', available: true, enabled: true, frequency: 'daily' },
        { engine: 'openai-web-search', mode: 'web_search', available: true, enabled: true, frequency: 'daily' },
        { engine: 'perplexity-web-search', mode: 'web_search', available: false, enabled: true, frequency: 'daily' },
        { engine: 'exa-answer', mode: 'web_search', available: true, enabled: true, frequency: 'daily' },
        { engine: 'claude-no-search', mode: 'no_search', available: true, enabled: false, frequency: 'daily' },
        { engine: 'openai-no-search', mode: 'no_search', available: true, enabled: false, frequency: 'daily' },
    ],
}

const CONFIGURED_CONTEXT: AEOSetupContextApi = {
    ...CONTEXT,
    websites: [{ domain: 'hedgebox.net', source: 'own_brand', pageviews: null }],
    own_domains: ['hedgebox.net'],
    active_prompts: 20,
    keywords: 18,
}

const RUNNING_JOB: AEOSetupJobApi = {
    id: '00000000-0000-4000-8000-000000000a01',
    status: 'pending',
    error: '',
    steps: [
        { step: 'brand', status: 'done', added: 1, detail: '' },
        { step: 'prompts', status: 'done', added: 20, detail: '' },
        { step: 'keywords', status: 'running', added: 0, detail: '' },
        { step: 'first_run', status: 'pending', added: 0, detail: '' },
    ],
}

// The count reads 0 until the engines load, so a snapshot waits for a real number.
const COUNTED = '[data-attr="content-autopilot-setup-cost-note"]:not([data-checks="0"])'

const mocks = (context: AEOSetupContextApi): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/projects/:team_id/aeo_setup/context/': () => [200, context],
            '/api/projects/:team_id/aeo_setup/:id/': () => [200, RUNNING_JOB],
            '/api/projects/:team_id/web_analytics_content_autopilot_profiles/': () => [
                200,
                { count: 0, next: null, previous: null, results: [] },
            ],
            '/api/projects/:team_id/aeo_prompts/': () => [200, { count: 0, next: null, previous: null, results: [] }],
            '/api/projects/:team_id/aeo_prompts/topics/': () => [200, []],
            '/api/projects/:team_id/aeo_engines/': () => [200, context.engines],
            '/api/projects/:team_id/aeo_keywords/': () => [200, []],
        },
    })

const meta: Meta<typeof ContentAutopilotSetupCard> = {
    title: 'Products/Web Analytics/Content autopilot/Setup',
    component: ContentAutopilotSetupCard,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
        mockDate: '2026-11-12',
    },
}

export default meta

const Frame = ({ children }: { children: JSX.Element }): JSX.Element => <div className="p-4 max-w-200">{children}</div>

export const EmptyState: StoryFn = () => (
    <Frame>
        <ContentAutopilotSetupCard />
    </Frame>
)
EmptyState.decorators = [mocks(CONTEXT)]
EmptyState.parameters = { testOptions: { waitForSelector: COUNTED } }

export const AiDataProcessingNotApproved: StoryFn = () => (
    <Frame>
        <ContentAutopilotSetupCard />
    </Frame>
)
AiDataProcessingNotApproved.decorators = [mocks({ ...CONTEXT, ai_data_processing_approved: false })]
AiDataProcessingNotApproved.parameters = {
    testOptions: { waitForSelector: '[data-attr="content-autopilot-setup-consent-banner"]' },
}

const RunningSetup = (): JSX.Element => {
    const { setJob } = useActions(contentAutopilotSetupLogic)
    useEffect(() => setJob(RUNNING_JOB), [setJob])
    return (
        <Frame>
            <ContentAutopilotSetupCard />
        </Frame>
    )
}

export const SetupRunning: StoryFn = () => <RunningSetup />
SetupRunning.decorators = [mocks(CONTEXT)]
SetupRunning.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
        waitForSelector: '[data-attr="content-autopilot-setup-progress"]',
    },
}

export const ConfiguredNoRunYet: StoryFn = () => (
    <Frame>
        <ContentAutopilotFirstRunCard prompts={20} />
    </Frame>
)
ConfiguredNoRunYet.decorators = [mocks(CONFIGURED_CONTEXT)]
ConfiguredNoRunYet.parameters = { testOptions: { waitForSelector: COUNTED } }
