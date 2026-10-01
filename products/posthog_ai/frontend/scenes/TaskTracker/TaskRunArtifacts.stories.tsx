import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { HttpResponse } from 'msw'
import { ReactNode, useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneLayout } from '~/layout/scenes/SceneLayout'
import { TodayShell } from '~/layout/today/TodayShell'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { mswDecorator } from '~/mocks/browser'
import type { MockSignature } from '~/mocks/utils'

import type { TaskRunArtifactResponseApi } from 'products/tasks/frontend/generated/api.schemas'
import { TaskRuntimeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { OriginProduct, Task, TaskRun, TaskRunEnvironment, TaskRunStatus } from '../../types/taskTypes'
import { TaskDetailPage } from './components/TaskDetailPage'
import { TaskRunTab } from './taskRunArtifacts'
import { taskRunArtifactsLogic } from './taskRunArtifactsLogic'

const TASK_ID = 'task-trials'
const RUN_ID = 'run-trials'

const REPORT_MARKDOWN = `# Trial starts dropped at the plan picker

Trial starts fell **18%** week over week. The loss sits almost entirely at the plan picker step. Other steps did not change.

| Step | Week of Sep 14 | Week of Sep 21 |
| --- | --- | --- |
| Pricing | 100% | 100% |
| Plan picker | 62% | 44% |
| Details | 48% | 35% |
| Trial started | 41% | 30% |

## What happened

The release on Tuesday changed the plan picker layout. The start trial button now sits below the fold at 1366 × 768, the most common laptop size in this funnel. Wide screens do not show the drop.

## Why

- Recordings show people scroll the plan table, then leave without a click.
- The drop starts on the day of the release and holds all week.
- Mobile uses a different layout and did not change.

## Next steps

1. Pin the start trial button to the top of the plan table.
2. Run an A/B test on the change for one week.

![](https://example.com/markdown-pixel.png)
`

const CHART_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360" font-family="Inter, sans-serif">
<rect width="640" height="360" fill="#ffffff"/>
<text x="32" y="40" font-size="16" font-weight="600" fill="#151515">Conversion by funnel step</text>
<rect x="400" y="28" width="10" height="10" rx="2" fill="#1d4aff" fill-opacity="0.3"/><text x="416" y="37" font-size="11" fill="#5f5f5f">Week of Sep 14</text>
<rect x="516" y="28" width="10" height="10" rx="2" fill="#1d4aff"/><text x="532" y="37" font-size="11" fill="#5f5f5f">Week of Sep 21</text>
<g stroke="#e5e5e2"><line x1="64" y1="80" x2="608" y2="80"/><line x1="64" y1="140" x2="608" y2="140"/><line x1="64" y1="200" x2="608" y2="200"/><line x1="64" y1="260" x2="608" y2="260"/><line x1="64" y1="320" x2="608" y2="320"/></g>
<g font-size="10" fill="#8a8a8a" text-anchor="end"><text x="56" y="84">100%</text><text x="56" y="144">75%</text><text x="56" y="204">50%</text><text x="56" y="264">25%</text><text x="56" y="324">0%</text></g>
<g fill="#1d4aff" fill-opacity="0.3"><rect x="96" y="80" width="40" height="240" rx="3"/><rect x="232" y="171" width="40" height="149" rx="3"/><rect x="368" y="205" width="40" height="115" rx="3"/><rect x="504" y="222" width="40" height="98" rx="3"/></g>
<g fill="#1d4aff"><rect x="140" y="80" width="40" height="240" rx="3"/><rect x="276" y="214" width="40" height="106" rx="3"/><rect x="412" y="236" width="40" height="84" rx="3"/><rect x="548" y="248" width="40" height="72" rx="3"/></g>
<g font-size="11" fill="#5f5f5f" text-anchor="middle"><text x="138" y="342">Pricing</text><text x="274" y="342">Plan picker</text><text x="410" y="342">Details</text><text x="546" y="342">Trial started</text></g>
</svg>`

const WEEKS_CSV = `week,trial_starts,conversion
2026-08-31,1204,41%
2026-09-07,1188,40%
2026-09-14,1231,41%
2026-09-21,1009,30%
`

const SUMMARY_HTML = `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  body { margin: 0; font-family: Inter, system-ui, sans-serif; color: #151515; background: #fafaf9; }
  main { max-width: 760px; margin: 0 auto; padding: 32px 28px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  p { color: #5f5f5f; font-size: 13px; margin: 0 0 20px; }
  .step { display: grid; grid-template-columns: 120px 1fr 48px; align-items: center; gap: 12px; margin-bottom: 10px; font-size: 13px; }
  .track { height: 28px; border-radius: 6px; background: #eeeeea; overflow: hidden; }
  .bar { height: 100%; background: #1d4aff; border-radius: 6px; }
  .value { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
  .note { margin-top: 24px; padding: 12px 14px; border-radius: 8px; background: #fff4e5; color: #7a4a00; font-size: 12px; }
</style>
</head>
<body>
<main>
  <h1>Trial funnel, week of Sep 21</h1>
  <p>Share of visitors who reach each step.</p>
  <div class="step"><span>Pricing</span><div class="track"><div class="bar" style="width: 100%"></div></div><span class="value">100%</span></div>
  <div class="step"><span>Plan picker</span><div class="track"><div class="bar" style="width: 44%"></div></div><span class="value">44%</span></div>
  <div class="step"><span>Details</span><div class="track"><div class="bar" style="width: 35%"></div></div><span class="value">35%</span></div>
  <div class="step"><span>Trial started</span><div class="track"><div class="bar" style="width: 30%"></div></div><span class="value">30%</span></div>
  <div class="note">The plan picker step drops from 62% to 44% against the week before.</div>
  <img src="https://example.com/html-pixel.png" alt="" width="1" height="1" />
</main>
</body>
</html>`

const ARTIFACTS: TaskRunArtifactResponseApi[] = [
    {
        id: 'artifact-report',
        name: 'trial-drop-report.md',
        type: 'output',
        source: 'agent_output',
        size: 6144,
        content_type: 'text/markdown',
        storage_path: 'tasks/artifacts/artifact-report',
        uploaded_at: '2026-09-28T18:18:00Z',
        uploaded_by: 'agent',
    },
    {
        id: 'artifact-summary',
        name: 'trial-funnel-summary.html',
        type: 'output',
        source: 'agent_output',
        size: 4096,
        content_type: 'text/html',
        storage_path: 'tasks/artifacts/artifact-summary',
        uploaded_at: '2026-09-28T18:16:00Z',
        uploaded_by: 'agent',
    },
    {
        id: 'artifact-chart',
        name: 'trial-starts-by-step.svg',
        type: 'output',
        source: 'agent_output',
        size: 8192,
        content_type: 'image/svg+xml',
        storage_path: 'tasks/artifacts/artifact-chart',
        uploaded_at: '2026-09-28T18:14:00Z',
        uploaded_by: 'agent',
    },
    {
        id: 'artifact-csv',
        name: 'trial-starts-by-week.csv',
        type: 'output',
        source: 'agent_output',
        size: 3072,
        content_type: 'text/csv',
        storage_path: 'tasks/artifacts/artifact-csv',
        uploaded_at: '2026-09-28T18:13:00Z',
        uploaded_by: 'agent',
    },
]

const CONTENT_BY_PATH: Record<string, string> = {
    'tasks/artifacts/artifact-report': REPORT_MARKDOWN,
    'tasks/artifacts/artifact-summary': SUMMARY_HTML,
    'tasks/artifacts/artifact-csv': WEEKS_CSV,
}

function mockRun(artifacts: TaskRunArtifactResponseApi[]): TaskRun {
    return {
        id: RUN_ID,
        task: TASK_ID,
        stage: null,
        branch: null,
        status: TaskRunStatus.COMPLETED,
        environment: TaskRunEnvironment.CLOUD,
        runtime_adapter: null,
        model: 'claude-opus-5-5',
        reasoning_effort: 'high',
        log_url: null,
        error_message: null,
        output: null,
        task_summary: null,
        task_tags: [],
        state: {},
        artifacts,
        created_at: '2026-09-28T17:42:00Z',
        updated_at: '2026-09-28T18:19:00Z',
        completed_at: '2026-09-28T18:19:00Z',
    } as TaskRun
}

function mockTask(run: TaskRun): Task {
    return {
        id: TASK_ID,
        task_number: 12,
        slug: 'TASK-12',
        title: 'Investigate the drop in trial starts',
        description: 'Trial starts dropped last week. Find the step where people leave and write it up for the team.',
        origin_product: OriginProduct.USER_CREATED,
        runtime: TaskRuntimeEnumApi.Acp,
        repository: null,
        github_integration: null,
        signal_report: null,
        json_schema: null,
        internal: false,
        latest_run: run,
        created_at: '2026-09-28T17:42:00Z',
        updated_at: '2026-09-28T18:19:00Z',
        created_by: { id: 1, uuid: 'user-uuid', distinct_id: 'user-1', first_name: 'Ada', email: 'ada@example.com' },
    } as Task
}

function logLine(update: Record<string, unknown>, timestamp: string): string {
    return JSON.stringify({
        type: 'notification',
        timestamp,
        notification: { method: 'session/update', params: { update } },
    })
}

const RUN_LOGS = [
    logLine(
        {
            sessionUpdate: 'user_message_chunk',
            content: {
                type: 'text',
                text: 'Trial starts dropped last week. Find the step where people leave and write it up for the team.',
            },
        },
        '2026-09-28T17:42:00Z'
    ),
    logLine(
        {
            sessionUpdate: 'tool_call',
            toolCallId: 'call-query',
            title: 'Run SQL query',
            status: 'completed',
            rawInput: { query: 'SELECT step, count() FROM trial_funnel GROUP BY step' },
        },
        '2026-09-28T17:50:00Z'
    ),
    logLine(
        {
            sessionUpdate: 'agent_message',
            content: {
                type: 'text',
                text: 'Trial starts fell 18% week over week. Almost all of the loss is at the plan picker step, which changed in the release on Tuesday. The new layout pushes the start trial button below the fold on laptop screens.\n\nI wrote a short report, an interactive funnel explorer, a chart of each step, and the weekly numbers as a CSV. Open the **Artifacts** tab to see them.',
            },
        },
        '2026-09-28T18:19:00Z'
    ),
].join('\n')

function taskMocks(artifacts: TaskRunArtifactResponseApi[]): {
    get: Record<string, MockSignature>
    post: Record<string, MockSignature>
} {
    const run = mockRun(artifacts)
    const task = mockTask(run)
    return {
        get: {
            '/api/code/invites/check-access/': { has_access: true, has_loops_access: false },
            '/api/projects/:team_id/tasks/': ({ request }: { request: Request }) => {
                const results = new URL(request.url).searchParams.get('pinned') ? [] : [task]
                return [200, { results, count: results.length, next: null, previous: null }]
            },
            [`/api/projects/:team_id/tasks/${TASK_ID}/`]: task,
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/`]: { count: 1, next: null, previous: null, results: [run] },
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/${RUN_ID}/`]: run,
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/${RUN_ID}/logs`]: () => new HttpResponse(RUN_LOGS),
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/${RUN_ID}/artifacts/artifact-chart/download/`]: () =>
                new HttpResponse(CHART_SVG, { headers: { 'Content-Type': 'image/svg+xml' } }),
            '/api/projects/:team_id/task_channels/': [],
            '/api/projects/:team_id/integrations/': { results: [] },
            '/api/environments/:team_id/conversations/': { results: [], next: null },
        },
        post: {
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/${RUN_ID}/artifacts/download/`]: async ({
                request,
            }: {
                request: Request
            }) => {
                const { storage_path } = (await request.json()) as { storage_path: string }
                return new HttpResponse(CONTENT_BY_PATH[storage_path] ?? '', {
                    headers: { 'Content-Type': 'text/plain' },
                })
            },
        },
    }
}

function TodayWebLayout({ children }: { children: ReactNode }): JSX.Element {
    const { pickPane } = useActions(todayShellLogic)
    const { user } = useValues(userLogic)
    useEffect(() => {
        pickPane('spaces')
    }, [pickPane])
    return (
        <div className="TodayAppLayout Today flex h-screen w-full overflow-hidden bg-surface-tertiary">
            {user ? <TodayShell className="left-nav" /> : null}
            <div className="@container/main-content-container main-content-container relative m-1 ml-0 flex min-w-0 flex-1 overflow-hidden rounded border border-primary">
                <main className="@container/main-content flex h-full flex-1 flex-col overflow-x-hidden overflow-y-auto rounded-t bg-[var(--color-bg-primary)] p-0">
                    <SceneLayout sceneConfig={{ layout: 'app-raw-no-header', name: 'Max', projectBased: true }}>
                        <div className="flex h-full grow flex-col overflow-hidden">{children}</div>
                    </SceneLayout>
                </main>
            </div>
        </div>
    )
}

function StoryPage({ tab = 'artifacts', artifactId }: { tab?: TaskRunTab; artifactId?: string }): JSX.Element {
    const { setActiveTab, selectArtifact } = useActions(taskRunArtifactsLogic({ taskId: TASK_ID }))
    useEffect(() => {
        if (artifactId) {
            selectArtifact(artifactId)
        }
        setActiveTab(tab)
    }, [tab, artifactId, setActiveTab, selectArtifact])
    return (
        <TodayWebLayout>
            <TaskDetailPage taskId={TASK_ID} isMobile={false} />
        </TodayWebLayout>
    )
}

const meta: Meta = {
    title: 'Scenes-App/Tasks/Artifacts',
    // No snapshots while the today-rail-nav layout is still changing quickly, the same as the Today stories.
    tags: ['test-skip'],
    decorators: [mswDecorator(taskMocks(ARTIFACTS))],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-28 18:30:00',
        pageUrl: urls.aiTask(TASK_ID),
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.TASKS],
    },
}
export default meta

type Story = StoryObj<{}>

export const MarkdownReport: Story = { render: () => <StoryPage artifactId="artifact-report" /> }

export const SandboxedHtml: Story = { render: () => <StoryPage artifactId="artifact-summary" /> }

export const Image: Story = { render: () => <StoryPage artifactId="artifact-chart" /> }

export const Csv: Story = { render: () => <StoryPage artifactId="artifact-csv" /> }

export const ConversationTab: Story = { render: () => <StoryPage tab="conversation" /> }

export const NoArtifacts: Story = {
    decorators: [mswDecorator(taskMocks([]))],
    render: () => <StoryPage />,
}

export const FlagOff: Story = {
    parameters: { featureFlags: [FEATURE_FLAGS.TASKS] },
    render: () => <StoryPage tab="conversation" />,
}
