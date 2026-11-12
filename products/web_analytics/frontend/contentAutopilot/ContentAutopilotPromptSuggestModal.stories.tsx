import type { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { AEOPromptSuggestionJobApi } from '../generated/api.schemas'
import { contentAutopilotPromptSuggestionsLogic } from './contentAutopilotPromptSuggestionsLogic'
import { ContentAutopilotPromptSuggestModal } from './ContentAutopilotPromptSuggestModal'

const JOB_ID = '00000000-0000-4000-8000-000000000901'

const PENDING_JOB: AEOPromptSuggestionJobApi = { id: JOB_ID, status: 'pending', suggestions: [], error: '' }

const COMPLETED_JOB: AEOPromptSuggestionJobApi = {
    id: JOB_ID,
    status: 'completed',
    error: '',
    suggestions: [
        {
            prompt: 'What is the best file sharing app for a small design agency?',
            topic: 'File sharing',
            circle: 'battleground',
            funnel_stage: 'bottom',
            branded: false,
            reason: 'Agencies compare tools before they buy seats for the team.',
        },
        {
            prompt: 'How can I send large video files to clients without them making an account?',
            topic: 'Client delivery',
            circle: 'differentiation',
            funnel_stage: 'middle',
            branded: false,
            reason: 'Guest links are a common reason to switch tools.',
        },
        {
            prompt: 'Which cloud storage tools have the best version history for documents?',
            topic: 'File sharing',
            circle: 'vulnerability',
            funnel_stage: 'middle',
            branded: false,
            reason: 'Buyers who need audit trails often pick a competitor here.',
        },
        {
            prompt: 'Is there a free alternative to paid cloud storage for students?',
            topic: 'Pricing',
            circle: 'table_stakes',
            funnel_stage: 'top',
            branded: false,
            reason: 'Price-sensitive buyers start with free plans.',
        },
        {
            prompt: 'What is Hedgebox and how does it compare to Dropbox?',
            topic: 'Brand',
            circle: 'branded',
            funnel_stage: 'middle',
            branded: true,
            reason: 'Checks how assistants describe the brand next to a competitor.',
        },
    ],
}

const meta: Meta<typeof ContentAutopilotPromptSuggestModal> = {
    title: 'Products/Web Analytics/Content autopilot/Suggest prompts',
    component: ContentAutopilotPromptSuggestModal,
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/web_analytics_content_autopilot_profiles/': () => [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
                '/api/projects/:team_id/aeo_prompts/': () => [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
                '/api/projects/:team_id/aeo_prompts/topics/': () => [200, []],
                '/api/projects/:team_id/aeo_prompts/suggest/:job_id/': () => [200, PENDING_JOB],
            },
        }),
    ],
}

export default meta

const SuggestStory = ({ job }: { job?: AEOPromptSuggestionJobApi }): JSX.Element => {
    const { openSuggest, setForm, setJob } = useActions(contentAutopilotPromptSuggestionsLogic)
    useEffect(() => {
        setForm({ domain: 'hedgebox.net', brand: 'Hedgebox', competitors: ['Dropbox', 'Box'] })
        openSuggest()
        if (job) {
            setJob(job)
        }
    }, [openSuggest, setForm, setJob, job])
    return <ContentAutopilotPromptSuggestModal />
}

export const Form: StoryFn = () => <SuggestStory />

export const Working: StoryFn = () => <SuggestStory job={PENDING_JOB} />
Working.parameters = { testOptions: { snapshotBrowsers: [], waitForLoadersToDisappear: false } }

export const Review: StoryFn = () => <SuggestStory job={COMPLETED_JOB} />
