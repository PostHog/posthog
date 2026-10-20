import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { TaskBasicApi, TaskRunArtifactResponseApi, TaskRuntimeEnumApi } from '../generated/api.schemas'
import { SpaceFeedCard } from './SpaceFeedCard'

const SPACE_ID = 'space-growth'

function file(name: string, uploadedAt: string, contentType?: string): TaskRunArtifactResponseApi {
    return {
        id: `artifact-${name}`,
        name,
        type: 'output',
        source: 'agent_output',
        storage_path: `tasks/artifacts/${name}`,
        content_type: contentType,
        uploaded_at: uploadedAt,
    }
}

function session(id: string, title: string, artifacts: TaskRunArtifactResponseApi[]): TaskBasicApi {
    return {
        id,
        task_number: 12,
        slug: id,
        title,
        title_manually_set: true,
        origin_product: 'user_created',
        runtime: TaskRuntimeEnumApi.Acp,
        repository: null,
        repositories: [],
        github_integration: null,
        github_user_integration: null,
        signal_report: null,
        json_schema: null,
        internal: false,
        archived: false,
        archived_at: null,
        ci_prompt: null,
        channel: SPACE_ID,
        slack_thread_references: [],
        description_preview: 'Find out why trial starts fell last week and write up what changed.',
        created_at: '2026-09-28T14:00:00Z',
        updated_at: '2026-09-28T16:00:00Z',
        last_activity_at: '2026-09-28T16:00:00Z',
        latest_run: {
            id: `${id}-run`,
            task: id,
            stage: null,
            branch: null,
            status: 'completed',
            environment: 'cloud',
            error_message: null,
            output: null,
            task_summary: null,
            task_tags: [],
            state: {},
            artifacts,
        },
    }
}

const ONE_FILE = session('session-one-file', 'Weekly signups summary', [
    file('signups-summary.md', '2026-09-28T15:00:00Z', 'text/markdown'),
])

const MANY_FILES = session('session-many-files', 'Trial starts dropped at the plan picker', [
    file('trial-starts-report.md', '2026-09-28T15:50:00Z', 'text/markdown'),
    file('trial-funnel-summary.html', '2026-09-28T15:40:00Z', 'text/html'),
    file('trial-starts-by-week.csv', '2026-09-28T15:30:00Z', 'text/csv'),
    file('trial-starts-by-step.svg', '2026-09-28T15:20:00Z', 'image/svg+xml'),
    file('plan-picker-walkthrough.mp4', '2026-09-28T15:10:00Z', 'video/mp4'),
])

const NO_FILES = session('session-no-files', 'Check the pricing page events', [])

const meta: Meta = {
    title: 'Scenes-App/Tasks/Space feed card',
    // No snapshots while the today-rail-nav layout is still changing quickly, the same as the Today stories.
    tags: ['test-skip'],
    decorators: [mswDecorator({})],
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-09-28 18:30:00',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.TASKS],
    },
}
export default meta

type Story = StoryObj<{}>

export const ArtifactChips: Story = {
    render: () => (
        <div className="Today flex max-w-[720px] flex-col">
            {[MANY_FILES, ONE_FILE, NO_FILES].map((task) => (
                <SpaceFeedCard
                    key={task.id}
                    spaceId={SPACE_ID}
                    task={task}
                    pinned={false}
                    unread={false}
                    repository={null}
                />
            ))}
        </div>
    ),
}
