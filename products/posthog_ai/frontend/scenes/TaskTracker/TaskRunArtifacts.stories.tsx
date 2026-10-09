import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
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

import type {
    TaskRunArtifactResponseApi,
    TaskRunLivingArtifactResponseApi,
} from 'products/tasks/frontend/generated/api.schemas'
import { TaskRuntimeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { expect, userEvent } from 'storybook/test'

import { OriginProduct, Task, TaskRun, TaskRunEnvironment, TaskRunStatus } from '../../types/taskTypes'
import { TaskDetailPage } from './components/TaskDetailPage'
import { TaskRunTab } from './taskRunArtifacts'
import { taskRunArtifactsLogic } from './taskRunArtifactsLogic'

const TASK_ID = 'task-trials'
const RUN_ID = 'run-trials'
const EARLIER_RUN_ID = 'run-trials-earlier'

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

const REPORT_DRAFT_MARKDOWN = `# Trial starts dropped

Trial starts fell week over week. I am still checking which step lost the most people.
`

const REPORT_SECOND_DRAFT_MARKDOWN = `# Trial starts dropped at the plan picker

Trial starts fell **18%** week over week. The loss sits almost entirely at the plan picker step.

## Why

- Recordings show people scroll the plan table, then leave without a click.
`

const CHART_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 640 360" font-family="Inter, sans-serif">
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
  <button id="preview-action">Run chart action</button>
  <img src="https://example.com/html-pixel.png" alt="" width="1" height="1" />
</main>
<script>document.getElementById('preview-action').addEventListener('click', function () { this.textContent = 'Chart action ran' })</script>
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

// Earlier uploads of the report. The file list groups them with `artifact-report` by name.
const REPORT_OLDER_VERSIONS: TaskRunArtifactResponseApi[] = [
    {
        id: 'artifact-report-v2',
        name: 'trial-drop-report.md',
        type: 'output',
        source: 'agent_output',
        size: 4096,
        content_type: 'text/markdown',
        storage_path: 'tasks/artifacts/artifact-report-v2',
        uploaded_at: '2026-09-28T18:02:00Z',
        uploaded_by: 'agent',
    },
    {
        id: 'artifact-report-v1',
        name: 'trial-drop-report.md',
        type: 'output',
        source: 'agent_output',
        size: 1024,
        content_type: 'text/markdown',
        storage_path: 'tasks/artifacts/artifact-report-v1',
        uploaded_at: '2026-09-28T17:51:00Z',
        uploaded_by: 'agent',
    },
]

const REPORT_FILE_NAME = 'trial-drop-report.md'

// A two-second clip drawn on a canvas for this story: a square that moves across a light frame.
const WALKTHROUGH_WEBM_BASE64 =
    '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'

function objectReference(
    id: string,
    name: string,
    objectKind: string,
    objectId: string,
    uploadedAt: string
): TaskRunArtifactResponseApi {
    return {
        id,
        name,
        type: 'reference',
        source: 'posthog_object',
        uploaded_at: uploadedAt,
        uploaded_by: 'agent',
        metadata: {
            reference_type: 'posthog_object',
            object_kind: objectKind,
            object_id: objectId,
            source_message_ids: ['message-1'],
            occurrence_count: 1,
        },
    } as TaskRunArtifactResponseApi
}

const OBJECT_REFERENCES = [
    objectReference('phref_trial_funnel', 'Trial funnel by step', 'insight', 'aBcD1234', '2026-09-28T18:12:00Z'),
    objectReference('phref_growth', 'Growth review', 'dashboard', '42', '2026-09-28T18:11:00Z'),
    objectReference('phref_flag', 'new-plan-picker', 'flag', '7', '2026-09-28T18:10:00Z'),
    objectReference('phref_experiment', 'Plan picker layout test', 'experiment', '12', '2026-09-28T18:09:00Z'),
    objectReference('phref_cohort', 'Trial starters on laptops', 'cohort', '3', '2026-09-28T18:08:00Z'),
    objectReference('phref_survey', 'Plan picker feedback', 'survey', 'survey-plan-picker', '2026-09-28T18:07:00Z'),
    // No kind called `note` has a page, so this reference shows the card.
    objectReference('phref_note', 'Pricing notes', 'note', 'pricing-notes', '2026-09-28T18:06:00Z'),
]

const VIDEO_ARTIFACT: TaskRunArtifactResponseApi = {
    id: 'artifact-walkthrough',
    name: 'plan-picker-walkthrough.webm',
    type: 'output',
    source: 'agent_output',
    size: 7340,
    content_type: 'video/webm',
    storage_path: 'tasks/artifacts/artifact-walkthrough',
    uploaded_at: '2026-09-28T18:19:00Z',
    uploaded_by: 'agent',
}

const CONTENT_BY_PATH: Record<string, string> = {
    'tasks/artifacts/artifact-report': REPORT_MARKDOWN,
    'tasks/artifacts/artifact-report-v2': REPORT_SECOND_DRAFT_MARKDOWN,
    'tasks/artifacts/artifact-report-v1': REPORT_DRAFT_MARKDOWN,
    'tasks/artifacts/artifact-summary': SUMMARY_HTML,
    'tasks/artifacts/artifact-csv': WEEKS_CSV,
}

const EDITED_REPORT_MARKDOWN = `${REPORT_MARKDOWN}
## Owner

Ada owns the fix. The A/B test starts on Monday.
`

// A version the agent writes while the story's user edits the report.
const REPORT_NEWER_VERSION: TaskRunArtifactResponseApi = {
    id: 'artifact-report-v4',
    name: REPORT_FILE_NAME,
    type: 'output',
    source: 'agent_output',
    size: 7168,
    content_type: 'text/markdown',
    storage_path: 'tasks/artifacts/artifact-report-v4',
    uploaded_at: '2026-09-28T18:24:00Z',
    uploaded_by: 'agent',
}

// The conflict story sets this when it presses Save, so the run read after that holds the newer version.
let newerReportArrived = false

function mockRun(artifacts: TaskRunArtifactResponseApi[], id = RUN_ID): TaskRun {
    return {
        id,
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

/** With `resumed`, the files sit on an earlier run and the latest run has none, as after a resume. */
function taskMocks(
    artifacts: TaskRunArtifactResponseApi[],
    { resumed = false }: { resumed?: boolean } = {}
): {
    get: Record<string, MockSignature>
    post: Record<string, MockSignature>
} {
    const run = mockRun(resumed ? [] : artifacts)
    const earlierRun = mockRun(resumed ? artifacts : [], EARLIER_RUN_ID)
    const runs = resumed ? [run, earlierRun] : [run]
    const task = mockTask(run)
    return {
        get: {
            '/api/code/invites/check-access/': { has_access: true, has_loops_access: false },
            '/api/projects/:team_id/tasks/': ({ request }: { request: Request }) => {
                const results = new URL(request.url).searchParams.get('pinned') ? [] : [task]
                return [200, { results, count: results.length, next: null, previous: null }]
            },
            [`/api/projects/:team_id/tasks/${TASK_ID}/`]: task,
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/`]: {
                count: runs.length,
                next: null,
                previous: null,
                // The real runs list carries no artifact manifests.
                results: runs.map(({ artifacts: _artifacts, ...rest }) => rest),
            },
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/${RUN_ID}/`]: run,
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/${EARLIER_RUN_ID}/`]: earlierRun,
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/${RUN_ID}/logs`]: () => new HttpResponse(RUN_LOGS),
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/:run_id/artifacts/artifact-chart/download/`]: () =>
                new HttpResponse(CHART_SVG, { headers: { 'Content-Type': 'image/svg+xml' } }),
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/:run_id/artifacts/:artifact_id/preview/`]: {
                url: `data:text/html;charset=utf-8,${encodeURIComponent(SUMMARY_HTML)}`,
                scripts_available: true,
            },
            '/api/projects/:team_id/task_channels/': [],
            '/api/projects/:team_id/integrations/': { results: [] },
            '/api/environments/:team_id/conversations/': { results: [], next: null },
        },
        post: {
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/:run_id/artifacts/download/`]: async ({
                request,
            }: {
                request: Request
            }) => {
                const { storage_path } = (await request.json()) as { storage_path: string }
                if (storage_path === VIDEO_ARTIFACT.storage_path) {
                    const bytes = Uint8Array.from(atob(WALKTHROUGH_WEBM_BASE64), (char) => char.charCodeAt(0))
                    return new HttpResponse(bytes, { headers: { 'Content-Type': 'video/webm' } })
                }
                return new HttpResponse(CONTENT_BY_PATH[storage_path] ?? '', {
                    headers: { 'Content-Type': 'text/plain' },
                })
            },
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/:run_id/artifacts/dismiss/`]: { artifacts },
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

/** Opens the file in the editor once its text loads, types `draft`, and with `save` presses Save. */
interface StoryEdit {
    draft: string
    save?: boolean
}

function StoryPage({
    tab = 'artifacts',
    fileName,
    versionId,
    edit,
    commentsOpen = false,
}: {
    tab?: TaskRunTab
    fileName?: string
    versionId?: string
    edit?: StoryEdit
    commentsOpen?: boolean
}): JSX.Element {
    const { setActiveTab, selectArtifact, selectVersion, startEditing, setEditDraft, saveEdit, setCommentsOpen } =
        useActions(taskRunArtifactsLogic({ taskId: TASK_ID }))
    const { selectedText, isEditing } = useValues(taskRunArtifactsLogic({ taskId: TASK_ID }))
    useEffect(() => {
        if (fileName) {
            selectArtifact(fileName)
        }
        if (versionId) {
            selectVersion(versionId)
        }
        setActiveTab(tab)
        setCommentsOpen(commentsOpen)
    }, [tab, fileName, versionId, commentsOpen, setActiveTab, selectArtifact, selectVersion, setCommentsOpen])
    const textLoaded = typeof selectedText?.text === 'string'
    useEffect(() => {
        if (!edit || !textLoaded || isEditing) {
            return
        }
        startEditing()
        setEditDraft(edit.draft)
        if (edit.save) {
            newerReportArrived = true
            saveEdit()
        }
    }, [edit, textLoaded, isEditing, startEditing, setEditDraft, saveEdit])
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
    // Mocks go through parameters, not story decorators: a story decorator's mocks register before the meta's and lose.
    decorators: [mswDecorator({})],
    parameters: {
        msw: { mocks: taskMocks(ARTIFACTS) },
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-28 18:30:00',
        pageUrl: urls.aiTask(TASK_ID),
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.TASKS],
    },
}
export default meta

type Story = StoryObj<{}>

export const MarkdownReport: Story = { render: () => <StoryPage fileName={REPORT_FILE_NAME} /> }

export const SandboxedHtml: Story = { render: () => <StoryPage fileName="trial-funnel-summary.html" /> }

export const Image: Story = { render: () => <StoryPage fileName="trial-starts-by-step.svg" /> }

export const Csv: Story = { render: () => <StoryPage fileName="trial-starts-by-week.csv" /> }

export const Video: Story = {
    parameters: { msw: { mocks: taskMocks([VIDEO_ARTIFACT, ...ARTIFACTS]) } },
    render: () => <StoryPage fileName={VIDEO_ARTIFACT.name} />,
}

function objectMocks(): ReturnType<typeof taskMocks> {
    return taskMocks([...ARTIFACTS, ...OBJECT_REFERENCES])
}

export const PostHogObjects: Story = {
    parameters: { msw: { mocks: objectMocks() } },
    render: () => <StoryPage fileName="phref_trial_funnel" />,
}

export const PostHogObjectWithoutPage: Story = {
    parameters: { msw: { mocks: objectMocks() } },
    render: () => <StoryPage fileName="phref_note" />,
}

export const Versions: Story = {
    parameters: { msw: { mocks: taskMocks([...ARTIFACTS, ...REPORT_OLDER_VERSIONS]) } },
    render: () => <StoryPage fileName={REPORT_FILE_NAME} />,
}

export const OlderVersion: Story = {
    parameters: { msw: { mocks: taskMocks([...ARTIFACTS, ...REPORT_OLDER_VERSIONS]) } },
    render: () => <StoryPage fileName={REPORT_FILE_NAME} versionId="artifact-report-v1" />,
}

export const ConversationTab: Story = { render: () => <StoryPage tab="conversation" /> }

export const NoArtifacts: Story = {
    parameters: { msw: { mocks: taskMocks([]) } },
    render: () => <StoryPage />,
}

export const FlagOff: Story = {
    parameters: { featureFlags: [FEATURE_FLAGS.TASKS] },
    render: () => <StoryPage tab="conversation" />,
}

function livingDocument(
    id: string,
    name: string,
    adapter: TaskRunLivingArtifactResponseApi['adapter'],
    versions: Record<string, unknown>[]
): TaskRunLivingArtifactResponseApi {
    return {
        id,
        task_id: TASK_ID,
        run_id: RUN_ID,
        team_id: 1,
        name,
        artifact_type: adapter === 'slack_file' ? 'spreadsheet' : 'document',
        adapter,
        status: 'active',
        location: { kind: adapter },
        metadata: {},
        current_version: versions.length,
        versions,
        created_at: '2026-09-28T17:58:00Z',
        updated_at: String(versions[versions.length - 1].created_at),
    }
}

const LIVING_DOCUMENTS = [
    livingDocument('doc-weekly-trials', 'Weekly trial report', 'slack_canvas', [
        {
            version: 1,
            content: REPORT_DRAFT_MARKDOWN,
            content_type: 'text/markdown',
            created_at: '2026-09-28T17:58:00Z',
        },
        {
            version: 2,
            content: REPORT_SECOND_DRAFT_MARKDOWN,
            content_type: 'text/markdown',
            created_at: '2026-09-28T18:05:00Z',
        },
        { version: 3, content: REPORT_MARKDOWN, content_type: 'text/markdown', created_at: '2026-09-28T18:21:00Z' },
    ]),
    livingDocument('doc-trial-sheet', 'trial-starts-by-week.xlsx', 'slack_file', [
        {
            version: 1,
            size: 9216,
            content_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            location: { kind: 'slack_file', storage_path: 'tasks/living/doc-trial-sheet/trial-starts-by-week.v1.xlsx' },
            created_at: '2026-09-28T18:17:00Z',
        },
    ]),
    livingDocument('doc-trial-chart', 'trial-funnel-chart.svg', 'slack_file', [
        {
            version: 1,
            size: 3584,
            content_type: 'image/svg+xml',
            location: { kind: 'slack_file', storage_path: 'tasks/living/doc-trial-chart/trial-funnel-chart.v1.svg' },
            created_at: '2026-09-28T18:12:00Z',
        },
        {
            version: 2,
            size: 3712,
            content_type: 'image/svg+xml',
            location: { kind: 'slack_file', storage_path: 'tasks/living/doc-trial-chart/trial-funnel-chart.v2.svg' },
            created_at: '2026-09-28T18:19:00Z',
        },
    ]),
]

function livingMocks(): ReturnType<typeof taskMocks> {
    const mocks = taskMocks([...ARTIFACTS, ...OBJECT_REFERENCES])
    return {
        get: {
            ...mocks.get,
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/:run_id/living_artifacts/`]: {
                artifacts: LIVING_DOCUMENTS,
            },
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/:run_id/living_artifacts/doc-trial-chart/versions/:version/`]:
                () => new HttpResponse(CHART_SVG, { headers: { 'Content-Type': 'image/svg+xml' } }),
        },
        post: mocks.post,
    }
}

export const LivingArtifact: Story = {
    parameters: { msw: { mocks: livingMocks() } },
    render: () => <StoryPage fileName="living-doc-weekly-trials" />,
}

export const LivingSlackFile: Story = {
    parameters: { msw: { mocks: livingMocks() } },
    render: () => <StoryPage fileName="living-doc-trial-chart" />,
}

export const EditingMarkdown: Story = {
    render: () => <StoryPage fileName={REPORT_FILE_NAME} edit={{ draft: EDITED_REPORT_MARKDOWN }} />,
}

function conflictMocks(): ReturnType<typeof taskMocks> {
    const mocks = taskMocks(ARTIFACTS)
    return {
        get: {
            ...mocks.get,
            [`/api/projects/:team_id/tasks/${TASK_ID}/runs/${RUN_ID}/`]: () => [
                200,
                mockRun(newerReportArrived ? [REPORT_NEWER_VERSION, ...ARTIFACTS] : ARTIFACTS),
            ],
        },
        post: mocks.post,
    }
}

export const SaveConflict: Story = {
    parameters: { msw: { mocks: conflictMocks() } },
    beforeEach: () => {
        newerReportArrived = false
    },
    render: () => <StoryPage fileName={REPORT_FILE_NAME} edit={{ draft: EDITED_REPORT_MARKDOWN, save: true }} />,
}

export const ResumedTask: Story = {
    parameters: { msw: { mocks: taskMocks(ARTIFACTS, { resumed: true }) } },
    render: () => <StoryPage fileName={REPORT_FILE_NAME} />,
}

const REVIEWER = {
    id: 2,
    uuid: 'user-uuid-2',
    distinct_id: 'user-2',
    first_name: 'Jamie',
    last_name: 'Rivera',
    email: 'jamie@example.com',
}
const ANALYST = {
    id: 3,
    uuid: 'user-uuid-3',
    distinct_id: 'user-3',
    first_name: 'Priya',
    last_name: 'Shah',
    email: 'priya@example.com',
}

function artifactComment(
    id: string,
    itemId: string,
    createdBy: typeof REVIEWER,
    content: string,
    createdAt: string,
    itemContext: Record<string, unknown>,
    sourceComment: string | null = null
): Record<string, unknown> {
    return {
        id,
        created_by: createdBy,
        completed_by: null,
        slack_thread: null,
        version: 0,
        scope: 'task_artifact',
        item_id: itemId,
        item_context: { taskId: TASK_ID, ...itemContext },
        content,
        created_at: createdAt,
        completed_at: null,
        source_comment: sourceComment,
        deleted: false,
    }
}

// The stored offsets are made up, so the highlight has to find its quote by text, as a Desktop comment does.
const QUOTE = 'The start trial button now sits below the fold'
const ARTIFACT_COMMENTS = [
    artifactComment(
        'comment-quote',
        'artifact-report',
        REVIEWER,
        'Which screen sizes did you check?',
        '2026-09-28T18:22:00Z',
        {
            anchor: { kind: 'text', quote: QUOTE, prefix: '', suffix: '', start: 0, end: QUOTE.length },
        }
    ),
    artifactComment(
        'comment-quote-reply',
        'artifact-report',
        ANALYST,
        'Every laptop size in the funnel. 1366 × 768 has the most people.',
        '2026-09-28T18:24:00Z',
        {},
        'comment-quote'
    ),
    artifactComment(
        'comment-document',
        'artifact-report',
        ANALYST,
        'Can we share this with the growth team on Monday?',
        '2026-09-28T18:25:00Z',
        {
            anchor: { kind: 'document' },
        }
    ),
    artifactComment(
        'comment-resolved',
        'artifact-report',
        REVIEWER,
        'Add the week of Sep 7 to the table.',
        '2026-09-28T18:20:00Z',
        { anchor: { kind: 'document' } }
    ),
    artifactComment(
        'comment-resolved-state',
        'artifact-report',
        ANALYST,
        'Resolved this thread',
        '2026-09-28T18:21:00Z',
        { anchor: { kind: 'document' }, threadState: 'resolved' },
        'comment-resolved'
    ),
    artifactComment(
        'comment-pin-1',
        'artifact-chart',
        REVIEWER,
        'This bar looks too tall next to the others.',
        '2026-09-28T18:23:00Z',
        {
            anchor: { kind: 'region', x: 0.21, y: 0.2, width: 0.035, height: 0.035 },
        }
    ),
    artifactComment(
        'comment-pin-2',
        'artifact-chart',
        ANALYST,
        'Label the drop here so people see it at once.',
        '2026-09-28T18:26:00Z',
        {
            anchor: { kind: 'region', x: 0.44, y: 0.56, width: 0.035, height: 0.035 },
        }
    ),
]

function commentMocks(): ReturnType<typeof taskMocks> {
    const mocks = taskMocks(ARTIFACTS)
    // New comments are kept for the story's lifetime, so a comment made in the story shows in the list.
    const comments = [...ARTIFACT_COMMENTS]
    return {
        get: {
            ...mocks.get,
            '/api/projects/:team_id/comments/': ({ request }: { request: Request }) => {
                const itemId = new URL(request.url).searchParams.get('item_id')
                return [200, { results: comments.filter((comment) => comment.item_id === itemId), next: null }]
            },
        },
        post: {
            ...mocks.post,
            '/api/projects/:team_id/comments/': async ({ request }: { request: Request }) => {
                const body = (await request.json()) as Record<string, unknown>
                const saved = {
                    ...artifactComment(
                        `comment-new-${comments.length}`,
                        String(body.item_id),
                        REVIEWER,
                        String(body.content),
                        '2026-09-28T18:30:00Z',
                        {}
                    ),
                    ...body,
                }
                comments.push(saved)
                return [201, saved]
            },
        },
    }
}

export const MarkdownComments: Story = {
    parameters: { msw: { mocks: commentMocks() } },
    render: () => <StoryPage fileName={REPORT_FILE_NAME} commentsOpen />,
}

export const ImageCommentPins: Story = {
    parameters: { msw: { mocks: commentMocks() } },
    render: () => <StoryPage fileName="trial-starts-by-step.svg" commentsOpen />,
}

export const MarkdownCommentThread: Story = {
    parameters: { msw: { mocks: commentMocks() } },
    render: () => <StoryPage fileName={REPORT_FILE_NAME} />,
    play: async ({ canvasElement }) => {
        const highlight = await waitFor(
            () => {
                const element = canvasElement.querySelector<HTMLElement>(
                    '[data-attr="task-artifact-comment-highlight"]'
                )
                expect(element).not.toBeNull()
                return element!
            },
            { timeout: 10_000 }
        )
        await userEvent.click(highlight)
    },
}

export const ImageCommentThread: Story = {
    parameters: { msw: { mocks: commentMocks() } },
    render: () => <StoryPage fileName="trial-starts-by-step.svg" />,
    play: async ({ canvasElement }) => {
        const pin = await waitFor(
            () => {
                const element = canvasElement.querySelector<HTMLElement>(
                    '[data-attr="task-artifact-comment-pin-marker"]'
                )
                expect(element).not.toBeNull()
                return element!
            },
            { timeout: 10_000 }
        )
        await userEvent.click(pin)
    },
}
