import type { Meta, StoryObj } from '@storybook/react'

import type { UserInterviewSearchResultApi } from './generated/api.schemas'
import { SearchResults } from './UserInterviews'

const MOCK_RESULTS: UserInterviewSearchResultApi[] = [
    {
        interview_id: 'i-1',
        topic_id: 't-1',
        document_type: 'transcript',
        similarity: 0.92,
        interviewee_identifier: 'ben@tato.co',
        content_snippet:
            "I just use the MCP from Claude Code. Honestly I've never opened the PostHog web UI to make a chart — the agent does it faster and I trust it.",
        created_at: '2026-05-12T10:00:00Z',
    },
    {
        interview_id: 'i-2',
        topic_id: 't-1',
        document_type: 'summary',
        similarity: 0.84,
        interviewee_identifier: 'sanburose@moneygram.com',
        content_snippet:
            'Heavy MCP user. Prefers conversational queries over clicking through filters. Wants chart-saving via the MCP to be more obvious.',
        created_at: '2026-05-11T09:30:00Z',
    },
    {
        interview_id: 'i-3',
        topic_id: 't-1',
        document_type: 'transcript',
        similarity: 0.71,
        interviewee_identifier: 'paul@tailwindapp.com',
        content_snippet:
            "Most of my colleagues still use the web UI, but I'm a CLI person. The MCP fits my workflow because I'm already in my terminal all day.",
        created_at: '2026-05-10T16:00:00Z',
    },
    {
        interview_id: 'i-4',
        topic_id: null,
        document_type: 'summary',
        similarity: 0.58,
        interviewee_identifier: 'ricardocoutinho@konsi.com.br',
        content_snippet:
            'Detached interview (no topic linked). Discussed onboarding friction; did not finish the planned questions.',
        created_at: '2026-05-09T14:00:00Z',
    },
]

const meta: Meta<typeof SearchResults> = {
    title: 'Scenes-App/User Interviews/Search Results',
    component: SearchResults,
    parameters: {
        layout: 'padded',
    },
}
export default meta
type Story = StoryObj<typeof SearchResults>

export const WithResults: Story = {
    args: {
        results: MOCK_RESULTS,
        loading: false,
    },
}

export const LoadingFirstSearch: Story = {
    args: {
        results: [],
        loading: true,
    },
}

export const NoMatches: Story = {
    args: {
        results: [],
        loading: false,
    },
}

export const LoadingWithStaleResults: Story = {
    name: 'Loading with stale results (dimmed)',
    args: {
        results: MOCK_RESULTS,
        loading: true,
    },
}

export const SingleResult: Story = {
    args: {
        results: [MOCK_RESULTS[0]],
        loading: false,
    },
}

export const DetachedOnly: Story = {
    name: 'Detached results only (no clickable link)',
    args: {
        results: [MOCK_RESULTS[3]],
        loading: false,
    },
}
