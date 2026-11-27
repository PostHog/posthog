import type { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { AEOPromptApi, AEOSetupContextApi, AEOSetupJobApi } from '../generated/api.schemas'
import { AiVisibilitySetupWizard } from './AiVisibilitySetupWizard'
import { ContentAutopilot } from './ContentAutopilot'
import { ContentAutopilotFirstRunCard } from './ContentAutopilotFirstRunCard'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

const CONTEXT: AEOSetupContextApi = {
    websites: [
        { domain: 'hedgebox.net', source: 'pageviews', pageviews: 48210 },
        { domain: 'hedgebox-docs.net', source: 'pageviews', pageviews: 3120 },
    ],
    own_domains: [],
    active_prompts: 0,
    max_active_prompts: 100,
    paused_prompts: 0,
    keywords: 0,
    has_checks: false,
    ai_data_processing_approved: true,
    first_run_available: true,
    prompt_target: 20,
    prompt_count_max: 50,
    website_days: 7,
    first_run_checks: [],
    engines: [
        { engine: 'claude-web-search', mode: 'web_search', available: true, enabled: true, frequency: 'daily' },
        { engine: 'openai-web-search', mode: 'web_search', available: true, enabled: true, frequency: 'daily' },
        { engine: 'perplexity-web-search', mode: 'web_search', available: false, enabled: false, frequency: 'daily' },
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
        { step: 'first_run', status: 'done', added: 0, detail: '' },
        { step: 'keywords', status: 'running', added: 0, detail: '' },
    ],
}

const prompt = (id: number, text: string, topic: string, active = true): AEOPromptApi =>
    ({
        id: `00000000-0000-4000-8000-${String(id).padStart(12, '0')}`,
        prompt: text,
        topic,
        active,
    }) as AEOPromptApi

const PROMPTS: AEOPromptApi[] = [
    prompt(1, 'What is the best file sharing app for small teams?', 'File sharing'),
    prompt(2, 'Which cloud storage is easiest to share with clients?', 'File sharing'),
    prompt(3, 'How do I send large video files without email limits?', 'Large files', false),
    prompt(4, 'Is Hedgebox a good alternative to bigger cloud drives?', 'Alternatives'),
]

const KEYWORDS = [
    { id: '00000000-0000-4000-8000-0000000000b1', keyword: 'file sharing', created_at: '2026-11-12T00:00:00Z' },
    { id: '00000000-0000-4000-8000-0000000000b2', keyword: 'cloud storage', created_at: '2026-11-12T00:00:00Z' },
    { id: '00000000-0000-4000-8000-0000000000b3', keyword: 'large files', created_at: '2026-11-12T00:00:00Z' },
]

// The count reads 0 until the context loads, so a snapshot waits for a real number.
const COUNTED = '[data-attr="content-autopilot-setup-cost-note"]:not([data-checks="0"])'

const mocks = (context: AEOSetupContextApi): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/projects/:team_id/aeo_setup/context/': () => [200, context],
            '/api/projects/:team_id/aeo_setup/:id/': () => [200, RUNNING_JOB],
            '/api/projects/:team_id/aeo_prompts/': () => [
                200,
                { count: PROMPTS.length, next: null, previous: null, results: PROMPTS },
            ],
            '/api/projects/:team_id/aeo_prompts/topics/': () => [200, []],
            '/api/projects/:team_id/aeo_engines/': () => [200, context.engines],
            '/api/projects/:team_id/aeo_keywords/': () => [200, KEYWORDS],
        },
    })

const meta: Meta<typeof AiVisibilitySetupWizard> = {
    title: 'Products/Web Analytics/Content autopilot/Setup',
    component: AiVisibilitySetupWizard,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
        mockDate: '2026-11-12',
        // The wizard is one scene's flow, so its stories render and run without visual baselines.
        testOptions: { snapshotBrowsers: [] },
    },
}

export default meta

const Frame = ({ children }: { children: JSX.Element }): JSX.Element => <div className="p-4 max-w-200">{children}</div>

export const YourWebsite: StoryFn = () => (
    <Frame>
        <AiVisibilitySetupWizard step="website" />
    </Frame>
)
YourWebsite.decorators = [mocks(CONTEXT)]
YourWebsite.parameters = { testOptions: { waitForSelector: '[data-attr="content-autopilot-setup-domain"]' } }

export const AiDataProcessingNotApproved: StoryFn = () => (
    <Frame>
        <AiVisibilitySetupWizard step="website" />
    </Frame>
)
AiDataProcessingNotApproved.decorators = [mocks({ ...CONTEXT, ai_data_processing_approved: false })]
AiDataProcessingNotApproved.parameters = {
    testOptions: { waitForSelector: '[data-attr="content-autopilot-setup-consent-banner"]' },
}

const WithJob = ({ job, children }: { job: AEOSetupJobApi; children: JSX.Element }): JSX.Element => {
    const { setJob } = useActions(contentAutopilotSetupLogic)
    useEffect(() => setJob(job), [job, setJob])
    return <Frame>{children}</Frame>
}

export const SettingUp: StoryFn = () => (
    <WithJob job={RUNNING_JOB}>
        <AiVisibilitySetupWizard step="review" />
    </WithJob>
)
SettingUp.decorators = [mocks(CONTEXT)]
SettingUp.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
        waitForSelector: '[data-attr="ai-visibility-setup-checklist"]',
    },
}

export const FirstCheckNotRun: StoryFn = () => (
    <Frame>
        <AiVisibilitySetupWizard step="review" />
    </Frame>
)
FirstCheckNotRun.decorators = [mocks(CONFIGURED_CONTEXT)]
FirstCheckNotRun.parameters = { testOptions: { waitForSelector: '[data-attr="ai-visibility-setup-not-run"]' } }

export const Review: StoryFn = () => (
    <Frame>
        <AiVisibilitySetupWizard step="review" />
    </Frame>
)
Review.decorators = [mocks(CONFIGURED_CONTEXT)]
Review.parameters = { testOptions: { waitForSelector: '[data-attr="ai-visibility-setup-review-keyword"]' } }

// The scene shows the error in place of setup, since the wizard can't open without the context.
export const ContextLoadError: StoryFn = () => (
    <Frame>
        <ContentAutopilot />
    </Frame>
)
ContextLoadError.decorators = [
    mswDecorator({
        get: { '/api/projects/:team_id/aeo_setup/context/': () => [500, { detail: 'Server error' }] },
    }),
]
ContextLoadError.parameters = {
    testOptions: { waitForSelector: '[data-attr="content-autopilot-setup-context-error"]' },
}

export const PromptsReadyAfterSetup: StoryFn = () => (
    <Frame>
        <ContentAutopilotFirstRunCard prompts={20} />
    </Frame>
)
PromptsReadyAfterSetup.decorators = [mocks(CONFIGURED_CONTEXT)]
PromptsReadyAfterSetup.parameters = { testOptions: { waitForSelector: COUNTED } }

export const PromptsSavedPaused: StoryFn = () => (
    <Frame>
        <ContentAutopilotFirstRunCard prompts={20} paused />
    </Frame>
)
PromptsSavedPaused.decorators = [mocks({ ...CONFIGURED_CONTEXT, active_prompts: 0, paused_prompts: 20 })]
PromptsSavedPaused.parameters = { testOptions: { waitForSelector: COUNTED } }
