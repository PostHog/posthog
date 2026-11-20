import type { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { AEOKeywordSuggestionJobApi } from '../generated/api.schemas'
import { contentAutopilotKeywordSuggestionsLogic } from './contentAutopilotKeywordSuggestionsLogic'
import { ContentAutopilotKeywordSuggestModal } from './ContentAutopilotKeywordSuggestModal'

const JOB_ID = '00000000-0000-4000-8000-000000000902'

const PENDING_JOB: AEOKeywordSuggestionJobApi = { id: JOB_ID, status: 'pending', suggestions: [], error: '' }

const COMPLETED_JOB: AEOKeywordSuggestionJobApi = {
    id: JOB_ID,
    status: 'completed',
    error: '',
    suggestions: [
        {
            keyword: 'file sharing',
            reason: 'The engines search for it on most questions about sending files.',
            searched_checks: 14,
        },
        {
            keyword: 'large file transfer',
            reason: 'Agencies ask how to send big video files to clients.',
            searched_checks: 6,
        },
        {
            keyword: 'version history',
            reason: 'Buyers who need audit trails compare tools on it.',
            searched_checks: 3,
        },
        {
            keyword: 'client portal',
            reason: 'A common reason small teams switch tools.',
            searched_checks: 0,
        },
        {
            keyword: 'cloud storage pricing',
            reason: 'Price-sensitive buyers start here before they pick a plan.',
            searched_checks: 1,
        },
    ],
}

const FAILED_JOB: AEOKeywordSuggestionJobApi = {
    id: JOB_ID,
    status: 'failed',
    suggestions: [],
    error: 'Keyword suggestions failed. Try again in a minute.',
}

const meta: Meta<typeof ContentAutopilotKeywordSuggestModal> = {
    title: 'Products/Web Analytics/Content autopilot/Suggest keywords',
    component: ContentAutopilotKeywordSuggestModal,
    parameters: {
        layout: 'fullscreen',
        mockDate: '2026-11-10',
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/web_analytics_content_autopilot_profiles/': () => [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
                '/api/projects/:team_id/aeo_keywords/': () => [200, []],
                '/api/projects/:team_id/aeo_keywords/report/': () => [200, null],
                '/api/projects/:team_id/aeo_keywords/modifiers/': () => [200, null],
                '/api/projects/:team_id/aeo_keywords/suggest/:job_id/': () => [200, PENDING_JOB],
            },
        }),
    ],
}

export default meta

const SuggestStory = ({ job }: { job?: AEOKeywordSuggestionJobApi }): JSX.Element => {
    const { openSuggest, setForm, setJob } = useActions(contentAutopilotKeywordSuggestionsLogic)
    useEffect(() => {
        setForm({ domain: 'hedgebox.net', brand: 'Hedgebox' })
        openSuggest()
        if (job) {
            setJob(job)
        }
    }, [openSuggest, setForm, setJob, job])
    return <ContentAutopilotKeywordSuggestModal />
}

export const Form: StoryFn = () => <SuggestStory />
Form.parameters = { testOptions: { waitForSelector: 'text=Number of keywords' } }

export const Working: StoryFn = () => <SuggestStory job={PENDING_JOB} />
Working.parameters = {
    testOptions: { waitForLoadersToDisappear: false, waitForSelector: 'text=Finding keywords for hedgebox.net' },
}

export const Review: StoryFn = () => <SuggestStory job={COMPLETED_JOB} />
Review.parameters = { testOptions: { waitForSelector: 'text=large file transfer' } }

export const Failed: StoryFn = () => <SuggestStory job={FAILED_JOB} />
Failed.parameters = { testOptions: { waitForSelector: 'text=Keyword suggestions failed' } }
