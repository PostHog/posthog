import type { Meta, StoryObj } from '@storybook/react'

import { ArtefactLogList } from './ArtefactLogList'

const predecessor = 'https://github.com/example/repo/pull/1'
const retained = 'https://github.com/example/repo/pull/2'
const replacement = 'https://github.com/example/repo/pull/3'

const meta: Meta<typeof ArtefactLogList> = {
    title: 'Scenes-App/Signals/ArtefactLogList',
    component: ArtefactLogList,
    parameters: { layout: 'padded' },
    args: {
        reportId: 'example-report',
        artefacts: [
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
            <div className="max-w-[520px]">
                <Story />
            </div>
        ),
    ],
}
