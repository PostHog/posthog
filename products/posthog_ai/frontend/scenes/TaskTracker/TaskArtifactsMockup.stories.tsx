import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { HttpResponse } from 'msw'
import { ReactNode, useEffect, useState } from 'react'

import {
    IconChevronLeft,
    IconChevronRight,
    IconCode,
    IconComment,
    IconDatabase,
    IconDocument,
    IconDownload,
    IconExternal,
    IconImage,
    IconLock,
} from '@posthog/icons'
import { LemonButton, LemonTable, LemonTabs, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneLayout } from '~/layout/scenes/SceneLayout'
import { TodayShell } from '~/layout/today/TodayShell'
import { TodayRailPane, todayShellLogic } from '~/layout/today/todayShellLogic'
import { mswDecorator } from '~/mocks/browser'
import type { MockSignature } from '~/mocks/utils'

import type { TaskRunArtifactResponseApi } from 'products/tasks/frontend/generated/api.schemas'
import { TaskRuntimeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { DebugLogsMenu } from '../../components/DebugLogsMenu'
import { OriginProduct, Task, TaskRun, TaskRunEnvironment, TaskRunStatus } from '../../types/taskTypes'
import { TaskRunLog } from './components/TaskRunLog'
import { TaskRunSceneShell } from './components/TaskRunSceneShell'
import { taskDetailSceneLogic } from './taskDetailSceneLogic'

type SessionTab = 'conversation' | 'artifacts'
type PreviewKind = 'markdown' | 'html' | 'image' | 'csv'

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

const WEEKS = [
    { week: '2026-08-31', trial_starts: 1204, conversion: '41%' },
    { week: '2026-09-07', trial_starts: 1188, conversion: '40%' },
    { week: '2026-09-14', trial_starts: 1231, conversion: '41%' },
    { week: '2026-09-21', trial_starts: 1009, conversion: '30%' },
]

const EXPLORER_HTML = `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  body { margin: 0; font-family: Inter, system-ui, sans-serif; color: #151515; background: #fafaf9; }
  main { max-width: 760px; margin: 0 auto; padding: 32px 28px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  p { color: #5f5f5f; font-size: 13px; margin: 0 0 20px; }
  .weeks { display: flex; gap: 6px; margin-bottom: 20px; }
  .weeks button { font: inherit; font-size: 12px; padding: 6px 10px; border-radius: 6px; border: 1px solid #deded9; background: #fff; cursor: pointer; }
  .weeks button[aria-pressed="true"] { background: #151515; border-color: #151515; color: #fff; }
  .step { display: grid; grid-template-columns: 120px 1fr 48px; align-items: center; gap: 12px; margin-bottom: 10px; font-size: 13px; }
  .track { height: 28px; border-radius: 6px; background: #eeeeea; overflow: hidden; }
  .bar { height: 100%; background: #1d4aff; border-radius: 6px; transition: width 300ms ease; }
  .value { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
  .note { margin-top: 24px; padding: 12px 14px; border-radius: 8px; background: #fff4e5; color: #7a4a00; font-size: 12px; }
</style>
</head>
<body>
<main>
  <h1>Trial funnel explorer</h1>
  <p>Pick a week to see the share of visitors who reach each step.</p>
  <div class="weeks" id="weeks"></div>
  <div id="steps"></div>
  <div class="note">The plan picker step drops from 62% to 44% in the week of Sep 21.</div>
</main>
<script>
  const data = {
    'Sep 7': [100, 61, 47, 40],
    'Sep 14': [100, 62, 48, 41],
    'Sep 21': [100, 44, 35, 30],
  }
  const steps = ['Pricing', 'Plan picker', 'Details', 'Trial started']
  const weeks = document.getElementById('weeks')
  const list = document.getElementById('steps')
  list.innerHTML = steps.map((s, i) => '<div class="step"><span>' + s + '</span><div class="track"><div class="bar" id="bar' + i + '"></div></div><span class="value" id="val' + i + '"></span></div>').join('')
  function show(week) {
    data[week].forEach((v, i) => {
      document.getElementById('bar' + i).style.width = v + '%'
      document.getElementById('val' + i).textContent = v + '%'
    })
    for (const b of weeks.children) b.setAttribute('aria-pressed', String(b.textContent === week))
  }
  Object.keys(data).forEach((week) => {
    const b = document.createElement('button')
    b.textContent = week
    b.onclick = () => show(week)
    weeks.appendChild(b)
  })
  show('Sep 21')
</script>
</body>
</html>`

const ARTIFACTS: TaskRunArtifactResponseApi[] = [
    {
        id: 'artifact-report',
        name: 'trial-drop-report.md',
        type: 'artifact',
        source: 'agent_output',
        size: 6144,
        content_type: 'text/markdown',
        uploaded_at: '2026-09-28T18:18:00Z',
        uploaded_by: 'agent',
    },
    {
        id: 'artifact-explorer',
        name: 'trial-funnel-explorer.html',
        type: 'artifact',
        source: 'agent_output',
        size: 18432,
        content_type: 'text/html',
        uploaded_at: '2026-09-28T18:16:00Z',
        uploaded_by: 'agent',
    },
    {
        id: 'artifact-chart',
        name: 'trial-starts-by-step.png',
        type: 'artifact',
        source: 'agent_output',
        size: 86016,
        content_type: 'image/png',
        uploaded_at: '2026-09-28T18:14:00Z',
        uploaded_by: 'agent',
    },
    {
        id: 'artifact-csv',
        name: 'trial-starts-by-week.csv',
        type: 'artifact',
        source: 'agent_output',
        size: 3072,
        content_type: 'text/csv',
        uploaded_at: '2026-09-28T18:13:00Z',
        uploaded_by: 'agent',
    },
]

const COMMENT_COUNTS: Record<string, number> = { 'artifact-report': 2, 'artifact-csv': 1 }

function previewKind(artifact: TaskRunArtifactResponseApi): PreviewKind {
    if (artifact.content_type === 'text/html') {
        return 'html'
    }
    if (artifact.content_type?.startsWith('image/')) {
        return 'image'
    }
    if (artifact.content_type === 'text/csv') {
        return 'csv'
    }
    return 'markdown'
}

const KIND_LABEL: Record<PreviewKind, string> = { markdown: 'Markdown', html: 'HTML', image: 'Image', csv: 'CSV' }

function KindIcon({ kind }: { kind: PreviewKind }): JSX.Element {
    if (kind === 'html') {
        return <IconCode />
    }
    if (kind === 'image') {
        return <IconImage />
    }
    if (kind === 'csv') {
        return <IconDatabase />
    }
    return <IconDocument />
}

function formatSize(bytes = 0): string {
    return bytes < 1024 * 1024
        ? `${Math.max(1, Math.round(bytes / 1024))} KB`
        : `${(bytes / 1024 / 1024).toFixed(1)} MB`
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

function taskMocks(artifacts: TaskRunArtifactResponseApi[]): Record<string, MockSignature> {
    const run = mockRun(artifacts)
    const task = mockTask(run)
    return {
        '/api/code/invites/check-access/': { has_access: true, has_loops_access: false },
        '/api/projects/:team_id/tasks/': ({ request }: { request: Request }) => {
            const results = new URL(request.url).searchParams.get('pinned') ? [] : [task]
            return [200, { results, count: results.length, next: null, previous: null }]
        },
        [`/api/projects/:team_id/tasks/${TASK_ID}/`]: task,
        [`/api/projects/:team_id/tasks/${TASK_ID}/runs/`]: { count: 1, next: null, previous: null, results: [run] },
        [`/api/projects/:team_id/tasks/${TASK_ID}/runs/${RUN_ID}/`]: run,
        [`/api/projects/:team_id/tasks/${TASK_ID}/runs/${RUN_ID}/logs`]: () => new HttpResponse(RUN_LOGS),
        '/api/projects/:team_id/task_channels/': [],
        '/api/projects/:team_id/integrations/': { results: [] },
        '/api/environments/:team_id/conversations/': { results: [], next: null },
    }
}

function useObjectUrl(content: string, type: string): string | null {
    const [url, setUrl] = useState<string | null>(null)
    useEffect(() => {
        const next = URL.createObjectURL(new Blob([content], { type }))
        setUrl(next)
        return () => URL.revokeObjectURL(next)
    }, [content, type])
    return url
}

function SandboxedHtmlFrame({ src, name }: { src: string | null; name: string }): JSX.Element {
    return (
        <iframe
            className="size-full border-0 bg-white"
            sandbox="allow-scripts"
            referrerPolicy="no-referrer"
            src={src ?? 'about:blank'}
            title={`Preview of ${name}`}
        />
    )
}

function HtmlPreview({ name }: { name: string }): JSX.Element {
    const src = useObjectUrl(EXPLORER_HTML, 'text/html')
    return <SandboxedHtmlFrame src={src} name={name} />
}

function ImagePreview({ name }: { name: string }): JSX.Element {
    const src = useObjectUrl(CHART_SVG, 'image/svg+xml')
    return (
        <div className="flex min-h-full items-center justify-center p-8">
            {src && <img src={src} alt={name} className="max-w-full rounded border border-primary bg-white" />}
        </div>
    )
}

function CsvPreview(): JSX.Element {
    return (
        <div className="p-6">
            <LemonTable
                dataSource={WEEKS}
                rowKey="week"
                size="small"
                columns={[
                    {
                        title: 'week',
                        dataIndex: 'week',
                        render: (_, row) => <span className="font-mono">{row.week}</span>,
                    },
                    {
                        title: 'trial_starts',
                        dataIndex: 'trial_starts',
                        align: 'right',
                        render: (_, row) => <span className="font-mono">{row.trial_starts}</span>,
                    },
                    {
                        title: 'conversion',
                        dataIndex: 'conversion',
                        align: 'right',
                        render: (_, row) => <span className="font-mono">{row.conversion}</span>,
                    },
                ]}
            />
        </div>
    )
}

function MarkdownPreview(): JSX.Element {
    return (
        <div className="px-6 py-8">
            <article className="mx-auto max-w-3xl rounded-lg border border-primary bg-surface-primary px-10 py-8">
                <LemonMarkdown>{REPORT_MARKDOWN}</LemonMarkdown>
            </article>
        </div>
    )
}

function ArtifactPreview({ artifact }: { artifact: TaskRunArtifactResponseApi }): JSX.Element {
    const kind = previewKind(artifact)
    if (kind === 'html') {
        return <HtmlPreview name={artifact.name} />
    }
    if (kind === 'image') {
        return <ImagePreview name={artifact.name} />
    }
    if (kind === 'csv') {
        return <CsvPreview />
    }
    return <MarkdownPreview />
}

function ArtifactNav({
    artifacts,
    selectedId,
    onSelect,
}: {
    artifacts: TaskRunArtifactResponseApi[]
    selectedId: string
    onSelect: (id: string) => void
}): JSX.Element {
    return (
        <nav
            className="flex w-64 shrink-0 flex-col gap-px overflow-y-auto border-r border-primary p-2"
            aria-label="Artifacts"
        >
            <div className="flex items-center justify-between py-1 pl-2">
                <span className="text-xs font-semibold text-secondary">
                    <span>Files</span> <span>{artifacts.length}</span>
                </span>
                <LemonButton size="xsmall" icon={<IconDownload />} tooltip="Download all" />
            </div>
            {artifacts.map((artifact) => {
                const kind = previewKind(artifact)
                return (
                    <LemonButton
                        key={artifact.id}
                        fullWidth
                        size="small"
                        active={artifact.id === selectedId}
                        icon={<KindIcon kind={kind} />}
                        onClick={() => artifact.id && onSelect(artifact.id)}
                    >
                        <span className="flex min-w-0 flex-col py-0.5">
                            <span className="truncate">{artifact.name}</span>
                            <span className="text-xs font-normal text-secondary">
                                {`${KIND_LABEL[kind]} · ${formatSize(artifact.size)}`}
                            </span>
                        </span>
                    </LemonButton>
                )
            })}
        </nav>
    )
}

function ArtifactToolbar({
    artifact,
    index,
    total,
    onStep,
}: {
    artifact: TaskRunArtifactResponseApi
    index: number
    total: number
    onStep: (delta: number) => void
}): JSX.Element {
    const kind = previewKind(artifact)
    const comments = COMMENT_COUNTS[artifact.id ?? ''] ?? 0
    return (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-primary px-3 py-1.5">
            <span className="flex size-4 shrink-0 items-center text-secondary">
                <KindIcon kind={kind} />
            </span>
            <span className="min-w-0 truncate font-semibold">{artifact.name}</span>
            <span className="text-xs text-secondary">
                {`${formatSize(artifact.size)} · ${dayjs(artifact.uploaded_at).fromNow()}`}
            </span>
            {kind === 'html' && (
                <Tooltip title="This page runs in a sandbox. It cannot read your PostHog data, cookies or session.">
                    <LemonTag type="muted" icon={<IconLock />}>
                        Sandboxed
                    </LemonTag>
                </Tooltip>
            )}
            <div className="ml-auto flex items-center gap-1">
                <span className="px-1 text-xs text-secondary tabular-nums">{`${index + 1} of ${total}`}</span>
                <LemonButton
                    size="small"
                    icon={<IconChevronLeft />}
                    tooltip="Previous file"
                    onClick={() => onStep(-1)}
                />
                <LemonButton size="small" icon={<IconChevronRight />} tooltip="Next file" onClick={() => onStep(1)} />
                <LemonButton type="secondary" size="small" icon={<IconComment />}>
                    {comments === 0 ? 'Comment' : comments === 1 ? '1 comment' : `${comments} comments`}
                </LemonButton>
                <LemonButton size="small" icon={<IconDownload />} tooltip="Download" />
                <LemonButton size="small" icon={<IconExternal />} tooltip="Open in a new tab" />
            </div>
        </div>
    )
}

function ArtifactsWorkspace({
    artifacts,
    initialId,
    onShowConversation,
}: {
    artifacts: TaskRunArtifactResponseApi[]
    initialId?: string
    onShowConversation: () => void
}): JSX.Element {
    const [selectedId, setSelectedId] = useState(initialId ?? artifacts[0]?.id ?? '')
    if (artifacts.length === 0) {
        return (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 py-16 text-center">
                <span className="flex size-10 items-center justify-center rounded-full bg-surface-secondary text-xl text-secondary">
                    <IconDocument />
                </span>
                <h3 className="mb-0 text-base font-semibold">No artifacts yet</h3>
                <p className="mb-2 max-w-sm text-sm text-secondary">
                    Files that the agent writes in this task show here. Ask it for a report, a chart, a CSV or an HTML
                    page.
                </p>
                <LemonButton type="secondary" size="small" onClick={onShowConversation}>
                    Go to the conversation
                </LemonButton>
            </div>
        )
    }
    const index = Math.max(
        0,
        artifacts.findIndex((artifact) => artifact.id === selectedId)
    )
    const artifact = artifacts[index]
    const step = (delta: number): void => {
        const next = artifacts[(index + delta + artifacts.length) % artifacts.length]
        if (next.id) {
            setSelectedId(next.id)
        }
    }
    return (
        <div className="flex min-h-0 flex-1">
            <ArtifactNav artifacts={artifacts} selectedId={artifact.id ?? ''} onSelect={setSelectedId} />
            <section className="flex min-w-0 flex-1 flex-col">
                <ArtifactToolbar artifact={artifact} index={index} total={artifacts.length} onStep={step} />
                <div
                    className={cn(
                        'min-h-0 flex-1 bg-surface-secondary',
                        previewKind(artifact) === 'html' ? 'flex flex-col' : 'overflow-y-auto'
                    )}
                >
                    <ArtifactPreview artifact={artifact} />
                </div>
            </section>
        </div>
    )
}

function TaskPageWithArtifacts({
    initialTab,
    initialArtifactId,
}: {
    initialTab: SessionTab
    initialArtifactId?: string
}): JSX.Element {
    const logic = taskDetailSceneLogic({ taskId: TASK_ID })
    const { task, selectedRun, isHeaderLoading, taskError } = useValues(logic)
    const { loadTask } = useActions(logic)
    const [tab, setTab] = useState<SessionTab>(initialTab)
    const artifacts = (selectedRun?.artifacts ?? []).filter(
        (artifact) => artifact.source === 'agent_output' && !artifact.dismissed_at
    )
    return (
        <TaskRunSceneShell
            task={task}
            selectedRun={selectedRun}
            isHeaderLoading={isHeaderLoading}
            titleActions={
                <div className="flex flex-wrap items-center gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconExternal />}
                        className="hidden lg:inline-flex"
                    >
                        Open in PostHog Desktop
                    </LemonButton>
                    <DebugLogsMenu variant="lemon" />
                </div>
            }
            onArchive={() => {}}
            taskError={taskError}
            onRetry={loadTask}
            isMobile={false}
        >
            <LemonTabs
                activeKey={tab}
                onChange={setTab}
                barClassName="mb-0 px-4"
                tabs={[
                    { key: 'conversation', label: 'Conversation' },
                    {
                        key: 'artifacts',
                        label: (
                            <span className="flex items-center gap-1.5">
                                <span>Artifacts</span>
                                {artifacts.length > 0 && <span className="text-secondary">{artifacts.length}</span>}
                            </span>
                        ),
                    },
                ]}
            />
            {tab === 'conversation' ? (
                <TaskRunLog taskId={TASK_ID} />
            ) : (
                <ArtifactsWorkspace
                    artifacts={artifacts}
                    initialId={initialArtifactId}
                    onShowConversation={() => setTab('conversation')}
                />
            )}
        </TaskRunSceneShell>
    )
}

function useOpenPane(pane: TodayRailPane): void {
    const { pickPane } = useActions(todayShellLogic)
    useEffect(() => {
        pickPane(pane)
    }, [pane, pickPane])
}

function TodayWebLayout({ children }: { children: ReactNode }): JSX.Element {
    useOpenPane('spaces')
    const { user } = useValues(userLogic)
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

function StoryPage({ tab = 'artifacts', artifactId }: { tab?: SessionTab; artifactId?: string }): JSX.Element {
    return (
        <TodayWebLayout>
            <TaskPageWithArtifacts initialTab={tab} initialArtifactId={artifactId} />
        </TodayWebLayout>
    )
}

const meta: Meta = {
    title: 'Mockups/Tasks/Artifacts on web',
    tags: ['test-skip'],
    decorators: [mswDecorator({ get: taskMocks(ARTIFACTS) })],
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

export const SandboxedHtml: Story = { render: () => <StoryPage artifactId="artifact-explorer" /> }

export const Image: Story = { render: () => <StoryPage artifactId="artifact-chart" /> }

export const Csv: Story = { render: () => <StoryPage artifactId="artifact-csv" /> }

export const ConversationTab: Story = { render: () => <StoryPage tab="conversation" /> }

export const NoArtifacts: Story = {
    decorators: [mswDecorator({ get: taskMocks([]) })],
    render: () => <StoryPage />,
}
