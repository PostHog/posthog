import type { Meta, StoryObj } from '@storybook/react'

import { EnrichedReviewer, ReviewerSuggestionGroup } from '../../types'
import { SuggestedReviewersSectionMockup } from './SuggestedReviewersSectionMockup'

function reviewer(id: string, name: string, email: string, fields: Partial<EnrichedReviewer>): EnrichedReviewer {
    return {
        github_login: id,
        user_uuid: id,
        github_name: name,
        relevant_commits: [],
        user: { id: 1, uuid: id, first_name: name, last_name: '', email },
        ...fields,
    }
}

const codeHistorySuggestions: EnrichedReviewer[] = [
    reviewer('maya', 'Maya Rivera', 'maya@example.com', {
        source_label: 'Code history',
        explanation: 'Changed the checkout handler where this issue occurs.',
    }),
    reviewer('theo', 'Theo Brooks', 'theo@example.com', {
        source_label: 'Code history',
        explanation: 'Built the retry path used by this request.',
    }),
    reviewer('nina', 'Nina Park', 'nina@example.com', {
        source_label: 'Code history',
        explanation: 'Recently changed the affected transport.',
    }),
]

const teamGroup: ReviewerSuggestionGroup = {
    name: 'Runtime platform team',
    reason: 'This team owns the request parser.',
}

const teamSuggestions: EnrichedReviewer[] = [
    ['avery', 'Avery Chen'],
    ['jordan', 'Jordan Lee'],
    ['rowan', 'Rowan Patel'],
    ['casey', 'Casey Morgan'],
    ['taylor', 'Taylor Brooks'],
    ['morgan', 'Morgan Reed'],
    ['riley', 'Riley Davis'],
    ['devon', 'Devon Clark'],
].map(([id, name]) =>
    reviewer(id, name, `${id}@example.com`, {
        source_label: 'Runtime ownership scout',
        explanation: teamGroup.reason,
        reason: teamGroup.reason,
        suggestion_group: teamGroup,
    })
)

const meta: Meta<typeof SuggestedReviewersSectionMockup> = {
    title: 'Scenes-App/Inbox/Detail/Suggested reviewers mockup',
    component: SuggestedReviewersSectionMockup,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    decorators: [
        (Story, context) => (
            <div
                className={`${context.parameters.mockupWidth === 'narrow' ? 'w-[26rem] p-4' : 'w-[46rem] p-6'} max-w-[calc(100vw-2rem)] rounded border bg-primary`}
            >
                <Story />
            </div>
        ),
    ],
    args: {
        onAdd: () => undefined,
        onRemove: () => undefined,
    },
}

export default meta

type Story = StoryObj<typeof SuggestedReviewersSectionMockup>

export const CodeHistory: Story = {
    args: { suggestions: codeHistorySuggestions },
}

export const SharedTeamRationale: Story = {
    args: { suggestions: teamSuggestions },
}

export const MixedSources: Story = {
    args: {
        suggestions: [
            ...teamSuggestions,
            reviewer('quinn', 'Quinn Foster', 'quinn@example.com', {
                source_label: 'Added by teammate',
                reason: 'Added as a reviewer by Avery Chen on Jan 1, 2026',
                explanation: null,
            }),
        ],
    },
}

export const NarrowPanel: Story = {
    parameters: { mockupWidth: 'narrow' },
    args: { suggestions: [...teamSuggestions, ...codeHistorySuggestions.slice(0, 1)] },
}
