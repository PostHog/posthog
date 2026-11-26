import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { ErrorTrackingIssueTagDefinitionApi } from '../../generated/api.schemas'
import type { IssueTagState, IssueTagsFilter } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { IssueTagSelect } from './IssueTagSelect'

type TagDefinition = Pick<ErrorTrackingIssueTagDefinitionApi, 'key' | 'label' | 'description'>

const FEW_TAGS: TagDefinition[] = [
    { key: 'frontend', label: 'Frontend', description: 'The stack trace has a frame from browser code.' },
    { key: 'third_party', label: 'Third party', description: 'The top frame is in a vendor script.' },
    { key: 'payments', label: 'Payments', description: '' },
]

const MANY_TAGS: TagDefinition[] = [
    ...FEW_TAGS,
    ...[
        'Checkout',
        'Billing',
        'Auth',
        'Onboarding',
        'Search',
        'Mobile app',
        'A tag name that is too long to fit on one line',
        'Exports',
        'Webhooks',
    ].map((label) => ({
        key: label.toLowerCase().replace(/ /g, '_'),
        label,
        description: `Errors raised in ${label.toLowerCase()} code.`,
    })),
]

function TagSelectStory({
    definitions,
    initialIssueTags,
}: {
    definitions: TagDefinition[]
    initialIssueTags: IssueTagsFilter | null
}): JSX.Element {
    const [issueTags, setIssueTags] = useState(initialIssueTags)
    const setTagState = (key: string, state: IssueTagState | null): void => {
        const current = issueTags ?? { has: [], hasNot: [] }
        const next = { has: current.has.filter((k) => k !== key), hasNot: current.hasNot.filter((k) => k !== key) }
        if (state) {
            next[state] = [...next[state], key]
        }
        setIssueTags(next.has.length || next.hasNot.length ? next : null)
    }
    return (
        // The popover is in a portal and adds no size to #storybook-root. This box is big enough to hold it, so the
        // snapshot of the root shows the whole popover.
        <div className="min-h-120 w-84">
            <IssueTagSelect
                definitions={definitions}
                loading={false}
                issueTags={issueTags}
                onTagStateChange={setTagState}
                onClear={() => setIssueTags(null)}
                defaultOpen
            />
        </div>
    )
}

const meta: Meta<typeof TagSelectStory> = {
    title: 'ErrorTracking/IssueTagSelect',
    component: TagSelectStory,
    parameters: {
        layout: 'padded',
        testOptions: { waitForSelector: '[data-attr="error-tracking-issue-tag-filter-manage-rules"]' },
    },
}
export default meta

type Story = StoryObj<typeof TagSelectStory>

export const NoTagsSelected: Story = { args: { definitions: FEW_TAGS, initialIssueTags: null } }

export const HasAndHasNot: Story = {
    args: { definitions: FEW_TAGS, initialIssueTags: { has: ['frontend'], hasNot: ['third_party'] } },
}

export const ManyTags: Story = {
    args: { definitions: MANY_TAGS, initialIssueTags: { has: ['frontend', 'webhooks'], hasNot: ['auth'] } },
}
