import type { Meta, StoryObj } from '@storybook/react'

import { mockTask } from '../../__mocks__/inboxMocks'
import { ArtefactLogList } from './ArtefactLogList'

// A repository name with no hyphen gives the browser nothing to break on, so these URLs are what
// the narrow story has to keep inside the card.
const predecessor = 'https://github.com/exampleorg/exampleplatformservice/pull/48213'
const retained = 'https://github.com/exampleorg/exampleplatformservice/pull/48244'
const replacement = 'https://github.com/exampleorg/exampleplatformservice/pull/48261'

const meta: Meta<typeof ArtefactLogList> = {
    title: 'Scenes-App/Signals/ArtefactLogList',
    component: ArtefactLogList,
    parameters: { layout: 'padded' },
    args: {
        reportId: 'example-report',
        knownTasks: new Map([
            ['old-task', { ...mockTask('old-task'), title: 'Handle retries in the background worker' }],
            [
                'new-task',
                {
                    ...mockTask('new-task'),
                    title: 'Handle retries at the request boundary and preserve the original response',
                },
            ],
        ]),
        pullRequests: [predecessor, retained, replacement].map((url, index) => ({
            id: `pr-${index}`,
            url,
            state: index === 0 ? 'closed' : index === 1 ? 'unknown' : 'open',
            merged: false,
            claim_id: null,
            attached_at: null,
            attached_by: { kind: 'task', user: null, agent: null, task_id: index === 2 ? 'new-task' : 'old-task' },
        })),
        artefacts: [
            {
                id: 'pr-link',
                type: 'pull_request',
                created_at: '2026-09-14T10:14:00Z',
                content: { url: replacement },
            },
            {
                id: 'decision',
                type: 'implementation_decision',
                created_at: '2026-09-14T10:00:00Z',
                content: {
                    supersede: true,
                    reason: 'New evidence places the fix in the request handler.',
                    targets: [{ pr_url: predecessor }, { pr_url: retained }],
                },
            },
            {
                id: 'replacement',
                type: 'implementation_replacement',
                created_at: '2026-09-14T10:01:00Z',
                content: { decision: { targets: [{ pr_url: predecessor }, { pr_url: retained }] } },
            },
            {
                id: 'outcome',
                type: 'implementation_handover',
                created_at: '2026-09-14T10:15:00Z',
                content: {
                    status: 'needs_attention',
                    explanation: 'The replacement finished. Review the PRs left open.',
                    replacement_pr_urls: [replacement],
                    results: { [predecessor]: 'closed', [retained]: 'skipped' },
                },
            },
        ],
    },
}

export default meta
type Story = StoryObj<typeof meta>

export const ReplacementLifecycle: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            // The detail rail this list always renders in, at its pinned width and padding.
            <div className="w-[26rem] p-5">
                <Story />
            </div>
        ),
    ],
}
