import { Meta, StoryObj } from '@storybook/react'

import { ButtonGroup } from 'lib/ui/quill'

import { mswDecorator } from '~/mocks/browser'
import type { ErrorTrackingIssueTag } from '~/queries/schema/schema-general'

import { userEvent } from 'storybook/test'

import { IssueSeveritySelect } from '../IssueSeveritySelect'
import { IssueStatusSelect } from '../IssueStatusSelect'
import { IssueTagsButton } from './IssueTagsButton'

type Tag = Pick<ErrorTrackingIssueTag, 'key' | 'label'>

const RULE_TAGS: Tag[] = [
    { key: 'rule_frontend', label: 'Frontend' },
    { key: 'rule_checkout', label: 'Checkout' },
    { key: 'rule_long', label: 'Unhandled errors in old Safari and Firefox versions that customers still report' },
]

const MANY_TAGS: Tag[] = [
    ...RULE_TAGS,
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

function IssueTagsButtonStory({ tags }: { tags: Tag[] }): JSX.Element {
    return (
        // The popover opens below the button, so the box is tall enough to hold it in the snapshot.
        <div className="min-h-100">
            <ButtonGroup>
                <IssueStatusSelect status="active" onChange={() => {}} />
                <IssueSeveritySelect severity="high" onChange={() => {}} />
                <IssueTagsButton tags={tags} onTagClick={() => {}} />
            </ButtonGroup>
        </div>
    )
}

const meta: Meta<typeof IssueTagsButtonStory> = {
    title: 'ErrorTracking/IssueTagsButton',
    component: IssueTagsButtonStory,
    parameters: { layout: 'padded' },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/error_tracking/tag_rules/': {
                    results: RULE_TAGS.map((tag) => ({ key: tag.key })),
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof IssueTagsButtonStory>

export const NoTags: Story = {
    args: { tags: [] },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}

export const OneTag: Story = { args: { tags: [RULE_TAGS[0]] } }

export const ManyTagsOpen: Story = {
    args: { tags: MANY_TAGS },
    parameters: {
        testOptions: { waitForSelector: '[data-attr="error-tracking-issue-tags-button-manage-rules"]' },
    },
    play: async ({ canvasElement }) => {
        await userEvent.click(
            canvasElement.querySelector('[data-attr="error-tracking-issue-tags-button"]') as HTMLElement
        )
    },
}
