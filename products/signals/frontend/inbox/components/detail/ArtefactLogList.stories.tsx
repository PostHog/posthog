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
export const RevisionLimit: Story = {
    parameters: { mockDate: '2026-09-17T10:00:00Z' },
    args: {
        artefacts: [
            {
                id: 'capped-decision',
                type: 'implementation_decision',
                created_at: '2026-09-14T10:00:00Z',
                content: {
                    supersede: false,
                    blocked_reason: 'revision_limit',
                    reason: 'The rewrite was saved, but the content revision limit prevents another replacement.',
                },
            },
        ],
    },
}
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

/** A check's whole life in the log: scheduled, run, stopped, and retired without a verdict. */
const checkLifecycleArtefacts = [
    {
        id: 'check-expired',
        type: 'check_expired',
        created_at: '2026-10-27T09:00:00Z',
        content: {
            check_id: 'check-c',
            kind: 'metric_threshold',
            title: 'Confirm the export backlog stays clear',
            expired_at: '2026-10-27T09:00:00Z',
            last_run_at: null,
        },
    },
    {
        id: 'check-verdict',
        type: 'check_result',
        created_at: '2026-09-27T09:00:00Z',
        content: {
            check_id: 'check-a',
            kind: 'agent',
            title: 'Checkout errors stay at zero after the retry fix',
            outcome: 'failed',
            explanation: 'New events arrive on the same stack frame, with checkout traffic unchanged.',
        },
    },
    {
        id: 'check-cancelled',
        type: 'check_cancelled',
        created_at: '2026-09-21T09:00:00Z',
        content: {
            check_id: 'check-b',
            kind: 'metric_threshold',
            title: 'No new reports of the export timeout',
            reason: 'replaced_by_research',
        },
    },
    {
        id: 'check-scheduled-pending',
        type: 'check_scheduled',
        created_at: '2026-09-20T09:05:00Z',
        content: {
            check_id: 'check-b',
            kind: 'metric_threshold',
            title: 'No new reports of the export timeout',
            rationale: 'The timeout should stop once the queue drains.',
            next_run_at: '2026-09-27T09:00:00Z',
            arms_on_resolve: true,
            soak_minutes: 4320,
            runs: 1,
        },
    },
    {
        id: 'check-scheduled',
        type: 'check_scheduled',
        created_at: '2026-09-20T09:00:00Z',
        content: {
            check_id: 'check-a',
            kind: 'agent',
            title: 'Checkout errors stay at zero after the retry fix',
            rationale: 'Confirms no new checkout exceptions arrive after the retry fix ships.',
            next_run_at: '2026-09-27T09:00:00Z',
            arms_on_resolve: false,
            skill_name: 'signals-scout-error-tracking',
            runs: 2,
        },
    },
]

export const CheckLifecycle: Story = {
    parameters: { mockDate: '2026-10-28T10:00:00Z' },
    args: { artefacts: checkLifecycleArtefacts },
}
export const CheckLifecycleNarrow: Story = {
    parameters: { mockDate: '2026-10-28T10:00:00Z' },
    args: { artefacts: checkLifecycleArtefacts },
    decorators: [
        (Story) => (
            // The rail at the width it gets next to an open side panel.
            <div className="w-[20rem] p-5">
                <Story />
            </div>
        ),
    ],
}

/** The three link gates that hold automatic implementation back, and the link one of them acted on. */
const linkArtefacts = [
    {
        id: 'skip-plan-parent',
        type: 'autostart_skip',
        created_at: '2026-09-22T09:10:00Z',
        content: {
            skip_reason: 'plan_parent',
            detail: 'No work started here because other reports are part of this one and do the work.',
        },
    },
    {
        id: 'skip-dependency',
        type: 'autostart_skip',
        created_at: '2026-09-22T09:05:00Z',
        content: {
            skip_reason: 'blocked_by_dependency',
            linked_report_id: '0198c0de-0000-7000-8000-000000000002',
            detail: 'No work started here because a report this one depends on has no pull request yet.',
        },
    },
    {
        id: 'skip-duplicate',
        type: 'autostart_skip',
        created_at: '2026-09-22T09:00:00Z',
        content: {
            skip_reason: 'duplicate_of',
            linked_report_id: '0198c0de-0000-7000-8000-000000000001',
            detail: 'No work started here because this report duplicates another one that is already resolved or has a pull request.',
        },
    },
    {
        id: 'link-duplicate',
        type: 'report_link',
        created_at: '2026-09-22T08:55:00Z',
        content: {
            kind: 'duplicate_of',
            report_id: '0198c0de-0000-7000-8000-000000000001',
            reason: 'Same export timeout, already covered by the earlier report.',
        },
    },
]

export const LinkedReportGates: Story = {
    parameters: { mockDate: '2026-09-23T10:00:00Z' },
    args: { artefacts: linkArtefacts },
}
