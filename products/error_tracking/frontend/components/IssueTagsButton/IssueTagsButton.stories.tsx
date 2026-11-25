import { Meta, StoryObj } from '@storybook/react'

import { ButtonGroup } from 'lib/ui/quill'

import type { ErrorTrackingIssueTag } from '~/queries/schema/schema-general'

import { IssueSeveritySelect } from '../IssueSeveritySelect'
import { IssueStatusSelect } from '../IssueStatusSelect'
import { IssueTagsButton } from './IssueTagsButton'

type Tag = Pick<ErrorTrackingIssueTag, 'key' | 'label'>

const MANY_TAGS: Tag[] = [
    { key: 'rule_frontend', label: 'Frontend' },
    { key: 'rule_checkout', label: 'Checkout' },
    { key: 'rule_long', label: 'Unhandled errors in old Safari and Firefox versions that customers still report' },
    { key: 'cause_in_trace', label: 'Cause in trace' },
    ...[
        'Billing',
        'Auth',
        'Onboarding',
        'Search',
        'Mobile app',
        'Exports',
        'Webhooks',
        'Payments',
        'Notifications',
        'Uploads',
        'Settings',
        'Reports',
        'Third party',
        'Flaky',
    ].map((label) => ({
        key: label.toLowerCase().replace(/ /g, '_'),
        label,
    })),
]

function IssueTagsButtonStory({ tags, defaultOpen }: { tags: Tag[]; defaultOpen?: boolean }): JSX.Element {
    return (
        // The popover opens below the button, so the box is tall enough to hold it in the snapshot.
        <div className="min-h-100">
            <ButtonGroup>
                <IssueStatusSelect status="active" onChange={() => {}} />
                <IssueSeveritySelect severity="high" onChange={() => {}} />
                <IssueTagsButton tags={tags} onTagClick={() => {}} defaultOpen={defaultOpen} />
            </ButtonGroup>
        </div>
    )
}

const meta: Meta<typeof IssueTagsButtonStory> = {
    title: 'ErrorTracking/IssueTagsButton',
    component: IssueTagsButtonStory,
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj<typeof IssueTagsButtonStory>

export const NoTags: Story = {
    args: { tags: [] },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}

export const OneTag: Story = { args: { tags: [MANY_TAGS[0]] } }

export const ManyTagsOpen: Story = {
    args: { tags: MANY_TAGS, defaultOpen: true },
    parameters: {
        testOptions: {
            waitForSelector: '[data-attr="error-tracking-issue-tags-button-manage-rules"]',
            // The popover renders in a portal outside #storybook-root, so the snapshot takes the whole body.
            snapshotTargetSelector: 'body',
        },
    },
}
