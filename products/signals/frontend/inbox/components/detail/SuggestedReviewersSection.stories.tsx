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
        source_skill: 'signals-scout-runtime-ownership',
        source_label: 'Runtime ownership scout',
        explanation: sharedReason,
        reason: sharedReason,
    })
)

const longReason =
    'These reviewers maintain the request parser and retry handling. Review the long configuration path before release because it affects several report views.'

const longReasonSuggestions: EnrichedReviewer[] = [
    ['casey', 'Casey Morgan'],
    ['jamie', 'Jamie Kim'],
].map(([id, name]) =>
    reviewer(id, name, `${id}@example.com`, {
        source_skill: 'signals-scout-agent-feedback',
        source_label: 'Agent feedback scout',
        explanation: longReason,
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
            reviewer('solo', 'Solo Scout', 'solo@example.com', {
                source_skill: 'signals-scout-infrastructure-reliability',
                source_label: 'Infrastructure reliability and request processing ownership scout',
                explanation: 'Maintains the request path.',
            }),
            ...sharedReasonSuggestions.slice(0, 2).map((suggestion) => ({
                ...suggestion,
                source_label: 'Infrastructure reliability and request processing ownership scout',
            })),
        ],
    },
}

export const NarrowPanelMixedSources: Story = {
    parameters: { mockupWidth: 'narrow' },
    args: {
        suggestions: sharedReasonSuggestions.slice(0, 3).map((suggestion, index) => ({
            ...suggestion,
            source_skill: [
                'signals-scout-infrastructure-reliability',
                'signals-scout-application-request-lifecycle',
                'signals-scout-platform-runtime-observability',
            ][index],
            source_label: [
                'Infrastructure reliability and request processing ownership scout',
                'Application request lifecycle and transport ownership scout',
                'Platform runtime observability and incident response scout',
            ][index],
        })),
    },
}

export const NarrowPanelMixedProvenance: Story = {
    parameters: { mockupWidth: 'narrow' },
    args: {
        suggestions: [
            ...sharedReasonSuggestions.slice(0, 2),
            reviewer('maya', 'Maya Rivera', 'maya@example.com', {
                relevant_commits: [{ sha: 'abc123f', url: 'https://example.com/c/abc123f', reason: sharedReason }],
                source_label: 'Code history',
                explanation: sharedReason,
                reason: sharedReason,
            }),
        ],
    },
}

export const WidePanelLongReason: Story = {
    args: { suggestions: longReasonSuggestions },
}

export const NarrowPanelLongReason: Story = {
    parameters: { mockupWidth: 'narrow' },
    args: { suggestions: longReasonSuggestions },
}

export const GroupedAndIndividualReviewers: Story = {
    args: {
        suggestions: [
            ...sharedReasonSuggestions.slice(0, 5),
            reviewer('skyler', 'Skyler Ellis', 'skyler@example.com', {
                source_skill: 'signals-scout-runtime-ownership',
                source_label: 'Runtime ownership scout',
                explanation: 'Owns the report routing and review path.',
            }),
            reviewer('maya', 'Maya Rivera', 'maya@example.com', {
                source_label: 'Code history',
                explanation: 'Changed the request handler where this issue occurs.',
            }),
            reviewer('quinn', 'Quinn Foster', 'quinn@example.com', {
                source_skill: 'signals-scout-runtime-ownership',
                source_label: 'Runtime ownership scout',
                explanation: 'Joined the review path after a teammate correction.',
            }),
        ],
    },
}
