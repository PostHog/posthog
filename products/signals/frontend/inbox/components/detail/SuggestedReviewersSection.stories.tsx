import type { Meta, StoryObj } from '@storybook/react'

import { EnrichedReviewer } from '../../types'
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

const sharedReason = 'These reviewers maintain the request execution parser.'

const sharedReasonSuggestions: EnrichedReviewer[] = [
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
        explanation: sharedReason,
        reason: sharedReason,
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

export const SharedReason: Story = {
    args: { suggestions: sharedReasonSuggestions },
}

export const MixedSources: Story = {
    args: {
        suggestions: [
            ...sharedReasonSuggestions,
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
    args: {
        suggestions: [
            reviewer('unlinked', 'Unlinked author', '', {
                user: null,
                user_uuid: null,
                source_label: 'Code history',
                explanation:
                    'Changed example.com/services/request-processing/a-very-long-path-without-spaces/or-identifiers.',
            }),
            ...codeHistorySuggestions.slice(0, 1),
        ],
    },
}
