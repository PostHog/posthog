import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import { userEvent } from 'storybook/test'

import type { InboxSummaryApi } from '../../../generated/api.schemas'
import { InboxValueSummary } from './InboxValueSummary'

const summary: InboxSummaryApi = {
    period_start: '2026-09-13T12:00:00Z',
    period_end: '2026-09-20T12:00:00Z',
    merged_pr_count: 12,
    people_count: 5,
    participation_complete: true,
    pull_requests: Array.from({ length: 12 }, (_, index) => ({
        repository: index % 3 === 0 ? 'PostHog/posthog-js' : 'PostHog/posthog',
        number: 111094 - index,
        url: `https://github.com/${index % 3 === 0 ? 'PostHog/posthog-js' : 'PostHog/posthog'}/pull/${111094 - index}`,
    })),
    people: [
        { id: 1, login: 'sam-example' },
        { id: 2, login: 'alex-example' },
        { id: 3, login: 'riley-example' },
        { id: 4, login: 'taylor-example' },
        { id: 5, login: 'jordan-example' },
    ],
}

function SummaryStory({
    response = summary,
    failed = false,
}: {
    response?: InboxSummaryApi
    failed?: boolean
}): JSX.Element {
    useStorybookMocks({
        get: { '/api/projects/:team_id/signals/inbox_summary/': () => (failed ? [503, {}] : [200, response]) },
    })
    return <InboxValueSummary visible />
}

const meta: Meta = {
    title: 'Scenes-App/Inbox/ValueSummary',
    component: InboxValueSummary,
    parameters: {
        layout: 'fullscreen',
        mockDate: '2026-09-20T12:00:00Z',
        featureFlags: [FEATURE_FLAGS.SIGNALS_INBOX_VALUE_SUMMARY],
    },
}
export default meta
type Story = StoryObj

export const Complete: Story = { render: () => <SummaryStory /> }
export const UpdatingPeople: Story = {
    render: () => (
        <SummaryStory response={{ ...summary, people_count: null, participation_complete: false, people: null }} />
    ),
}
export const NoMerges: Story = {
    render: () => (
        <SummaryStory response={{ ...summary, merged_pr_count: 0, people_count: 0, pull_requests: [], people: [] }} />
    ),
}
export const Error: Story = { render: () => <SummaryStory failed /> }
export const Narrow: Story = {
    render: () => (
        <div className="w-[520px]">
            <SummaryStory />
        </div>
    ),
}
export const PullRequestsOpen: Story = {
    render: () => <SummaryStory />,
    play: async ({ canvas }) => {
        await userEvent.hover(await canvas.findByText('12 PRs'))
    },
}
export const PeopleOpen: Story = {
    render: () => (
        <div className="w-[520px]">
            <SummaryStory />
        </div>
    ),
    play: async ({ canvas }) => {
        await userEvent.hover(await canvas.findByText('5 people'))
    },
}
