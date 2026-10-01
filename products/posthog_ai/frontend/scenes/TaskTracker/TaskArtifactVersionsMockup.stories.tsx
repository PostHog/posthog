import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useState } from 'react'

import {
    IconChevronDown,
    IconChevronLeft,
    IconChevronRight,
    IconClockRewind,
    IconCode,
    IconDocument,
    IconDownload,
    IconImage,
    IconX,
} from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { cn } from 'lib/utils/css-classes'
import { userLogic } from 'scenes/userLogic'

import { SceneLayout } from '~/layout/scenes/SceneLayout'
import { TodayShell } from '~/layout/today/TodayShell'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { mswDecorator } from '~/mocks/browser'

import { TaskRuntimeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { OriginProduct, Task, TaskRun, TaskRunEnvironment, TaskRunStatus } from '../../types/taskTypes'
import { withStrictCsp } from './artifactHtml'
import { TaskRunSceneShell } from './components/TaskRunSceneShell'

type Kind = 'markdown' | 'html' | 'image'
type Option = 'menu' | 'nested' | 'history' | 'stepper'

interface Version {
    id: string
    uploadedAt: string
    uploadedBy: 'agent' | 'user'
    size: string
    content: string
}

interface MockFile {
    name: string
    kind: Kind
    /** Newest first. */
    versions: Version[]
}

const REPORT_V1 = `# Trial starts dropped

Trial starts fell week over week. I am still checking which step lost the most people.
`

const REPORT_V2 = `# Trial starts dropped at the plan picker

Trial starts fell **18%** week over week. The loss sits almost entirely at the plan picker step.

## Why

- Recordings show people scroll the plan table, then leave without a click.
`

const REPORT_V3 = `# Trial starts dropped at the plan picker

Trial starts fell **18%** week over week. The loss sits almost entirely at the plan picker step. Other steps did not change.

## Why

- Recordings show people scroll the plan table, then leave without a click.
- The drop starts on the day of the release and holds all week.

## Next steps

1. Pin the start trial button to the top of the plan table.
2. Run an A/B test on the change for one week.
`

function summaryHtml(planPicker: number): string {
    return `<!doctype html><html><head><style>
body { margin: 0; font-family: Inter, system-ui, sans-serif; color: #151515; background: #fafaf9; }
main { max-width: 720px; margin: 0 auto; padding: 32px 28px; }
h1 { font-size: 20px; margin: 0 0 16px; }
.step { display: grid; grid-template-columns: 120px 1fr 48px; align-items: center; gap: 12px; margin-bottom: 10px; font-size: 13px; }
.track { height: 24px; border-radius: 6px; background: #eeeeea; overflow: hidden; }
.bar { height: 100%; background: #1d4aff; border-radius: 6px; }
</style></head><body><main><h1>Trial funnel</h1>
<div class="step"><span>Pricing</span><div class="track"><div class="bar" style="width: 100%"></div></div><span>100%</span></div>
<div class="step"><span>Plan picker</span><div class="track"><div class="bar" style="width: ${planPicker}%"></div></div><span>${planPicker}%</span></div>
</main></body></html>`
}

const CHART_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 300" font-family="Inter, sans-serif">
<rect width="640" height="300" fill="#ffffff"/>
<text x="32" y="40" font-size="16" font-weight="600" fill="#151515">Conversion by funnel step</text>
<g fill="#1d4aff"><rect x="80" y="70" width="60" height="200" rx="4"/><rect x="230" y="160" width="60" height="110" rx="4"/><rect x="380" y="190" width="60" height="80" rx="4"/><rect x="530" y="205" width="60" height="65" rx="4"/></g>
</svg>`

const FILES: MockFile[] = [
    {
        name: 'trial-drop-report.md',
        kind: 'markdown',
        versions: [
            {
                id: 'report-3',
                uploadedAt: '2026-09-28T18:18:00Z',
                uploadedBy: 'agent',
                size: '6 KB',
                content: REPORT_V3,
            },
            {
                id: 'report-2',
                uploadedAt: '2026-09-28T18:02:00Z',
                uploadedBy: 'agent',
                size: '4 KB',
                content: REPORT_V2,
            },
            {
                id: 'report-1',
                uploadedAt: '2026-09-28T17:51:00Z',
                uploadedBy: 'agent',
                size: '1 KB',
                content: REPORT_V1,
            },
        ],
    },
    {
        name: 'trial-funnel-summary.html',
        kind: 'html',
        versions: [
            {
                id: 'summary-2',
                uploadedAt: '2026-09-28T18:16:00Z',
                uploadedBy: 'agent',
                size: '4 KB',
                content: summaryHtml(44),
            },
            {
                id: 'summary-1',
                uploadedAt: '2026-09-28T17:58:00Z',
                uploadedBy: 'agent',
                size: '4 KB',
                content: summaryHtml(48),
            },
        ],
    },
    {
        name: 'trial-starts-by-step.svg',
        kind: 'image',
        versions: [
            {
                id: 'chart-1',
                uploadedAt: '2026-09-28T18:14:00Z',
                uploadedBy: 'agent',
                size: '8 KB',
                content: CHART_SVG,
            },
        ],
    },
]

function KindIcon({ kind }: { kind: Kind }): JSX.Element {
    return kind === 'html' ? <IconCode /> : kind === 'image' ? <IconImage /> : <IconDocument />
}

function versionLabel(file: MockFile, index: number): string {
    return `Version ${file.versions.length - index}`
}

function when(version: Version): string {
    return dayjs(version.uploadedAt).fromNow()
}

function Preview({ file, version }: { file: MockFile; version: Version }): JSX.Element {
    if (file.kind === 'html') {
        return (
            <iframe
                className="size-full border-0 bg-white"
                sandbox=""
                referrerPolicy="no-referrer"
                srcDoc={withStrictCsp(version.content)}
                title={`Preview of ${file.name}`}
            />
        )
    }
    if (file.kind === 'image') {
        return (
            <div className="flex min-h-full items-center justify-center p-8">
                <img
                    src={`data:image/svg+xml;utf8,${encodeURIComponent(version.content)}`}
                    alt={file.name}
                    className="max-w-full rounded border border-primary bg-white"
                />
            </div>
        )
    }
    return (
        <div className="px-6 py-8">
            <article className="mx-auto max-w-3xl rounded-lg border border-primary bg-surface-primary px-10 py-8">
                <LemonMarkdown disableImages="all">{version.content}</LemonMarkdown>
            </article>
        </div>
    )
}

interface Selection {
    fileIndex: number
    versionIndex: number
}

interface PaneProps {
    option: Option
    selection: Selection
    select: (selection: Selection) => void
}

function FileNav({ option, selection, select }: PaneProps): JSX.Element {
    const [expanded, setExpanded] = useState<number | null>(selection.fileIndex)
    return (
        <nav
            className="flex w-64 shrink-0 flex-col gap-px overflow-y-auto border-r border-primary p-2"
            aria-label="Artifacts"
        >
            <span className="py-1 pl-2 text-xs font-semibold text-secondary">{`Files ${FILES.length}`}</span>
            {FILES.map((file, fileIndex) => {
                const latest = file.versions[0]
                const versioned = file.versions.length > 1
                const isSelected = selection.fileIndex === fileIndex
                const isExpanded = option === 'nested' && versioned && expanded === fileIndex
                return (
                    <div key={file.name} className="flex flex-col gap-px">
                        <LemonButton
                            fullWidth
                            size="small"
                            active={isSelected && (option !== 'nested' || !versioned)}
                            icon={<KindIcon kind={file.kind} />}
                            sideIcon={
                                option === 'nested' && versioned ? (
                                    <IconChevronDown
                                        className={cn('transition-transform', !isExpanded && '-rotate-90')}
                                    />
                                ) : undefined
                            }
                            onClick={() => {
                                select({ fileIndex, versionIndex: 0 })
                                if (option === 'nested' && versioned) {
                                    setExpanded(isExpanded ? null : fileIndex)
                                }
                            }}
                        >
                            <span className="flex min-w-0 flex-col py-0.5">
                                <span className="truncate">{file.name}</span>
                                <span className="flex items-center gap-1 text-xs font-normal text-secondary">
                                    {versioned && option !== 'nested' ? (
                                        <>
                                            <span>{`${latest.size} · ${when(latest)}`}</span>
                                            <LemonTag size="small" type="muted">{`v${file.versions.length}`}</LemonTag>
                                        </>
                                    ) : (
                                        <span>
                                            {versioned
                                                ? `${file.versions.length} versions · ${when(latest)}`
                                                : `${latest.size} · ${when(latest)}`}
                                        </span>
                                    )}
                                </span>
                            </span>
                        </LemonButton>
                        {isExpanded &&
                            file.versions.map((version, versionIndex) => (
                                <LemonButton
                                    key={version.id}
                                    fullWidth
                                    size="xsmall"
                                    className="pl-8"
                                    active={isSelected && selection.versionIndex === versionIndex}
                                    onClick={() => select({ fileIndex, versionIndex })}
                                >
                                    <span className="flex w-full items-center gap-2">
                                        <span className="font-normal">{versionLabel(file, versionIndex)}</span>
                                        {versionIndex === 0 && (
                                            <LemonTag size="small" type="success">
                                                Latest
                                            </LemonTag>
                                        )}
                                        <span className="ml-auto text-xs font-normal text-secondary">
                                            {when(version)}
                                        </span>
                                    </span>
                                </LemonButton>
                            ))}
                    </div>
                )
            })}
        </nav>
    )
}

function VersionControl({ option, selection, select }: PaneProps): JSX.Element | null {
    const file = FILES[selection.fileIndex]
    if (file.versions.length < 2) {
        return null
    }
    if (option === 'menu') {
        return (
            <LemonSelect
                size="small"
                value={selection.versionIndex}
                onChange={(versionIndex) => select({ ...selection, versionIndex })}
                options={file.versions.map((version, versionIndex) => ({
                    value: versionIndex,
                    label:
                        versionIndex === 0
                            ? `${versionLabel(file, versionIndex)} (latest)`
                            : versionLabel(file, versionIndex),
                    labelInMenu: (
                        <span className="flex w-56 items-center gap-2">
                            <span>{versionLabel(file, versionIndex)}</span>
                            {versionIndex === 0 && (
                                <LemonTag size="small" type="success">
                                    Latest
                                </LemonTag>
                            )}
                            <span className="ml-auto text-xs text-secondary">{when(version)}</span>
                        </span>
                    ),
                }))}
            />
        )
    }
    if (option === 'stepper') {
        const total = file.versions.length
        return (
            <span className="flex items-center gap-0.5 rounded border border-primary px-1">
                <LemonButton
                    size="xsmall"
                    icon={<IconChevronLeft />}
                    tooltip="Older version"
                    disabledReason={selection.versionIndex === total - 1 ? 'This is the first version' : undefined}
                    onClick={() => select({ ...selection, versionIndex: selection.versionIndex + 1 })}
                />
                <span className="px-1 text-xs tabular-nums">{`Version ${total - selection.versionIndex} of ${total}`}</span>
                <LemonButton
                    size="xsmall"
                    icon={<IconChevronRight />}
                    tooltip="Newer version"
                    disabledReason={selection.versionIndex === 0 ? 'This is the latest version' : undefined}
                    onClick={() => select({ ...selection, versionIndex: selection.versionIndex - 1 })}
                />
            </span>
        )
    }
    return null
}

function HistoryPanel({
    selection,
    select,
    onClose,
}: Omit<PaneProps, 'option'> & { onClose: () => void }): JSX.Element {
    const file = FILES[selection.fileIndex]
    return (
        <aside
            className="flex w-64 shrink-0 flex-col border-l border-primary bg-surface-primary"
            aria-label="Version history"
        >
            <div className="flex items-center gap-2 border-b border-primary px-3 py-2">
                <span className="font-semibold">Version history</span>
                <LemonButton className="ml-auto" size="xsmall" icon={<IconX />} tooltip="Close" onClick={onClose} />
            </div>
            <ol className="m-0 flex list-none flex-col gap-px p-2">
                {file.versions.map((version, versionIndex) => (
                    <li key={version.id}>
                        <LemonButton
                            fullWidth
                            size="small"
                            active={selection.versionIndex === versionIndex}
                            onClick={() => select({ ...selection, versionIndex })}
                        >
                            <span className="flex w-full flex-col py-0.5">
                                <span className="flex items-center gap-2">
                                    <span>{versionLabel(file, versionIndex)}</span>
                                    {versionIndex === 0 && (
                                        <LemonTag size="small" type="success">
                                            Latest
                                        </LemonTag>
                                    )}
                                </span>
                                <span className="text-xs font-normal text-secondary">
                                    {`${dayjs(version.uploadedAt).format('MMM D, HH:mm')} · ${
                                        version.uploadedBy === 'agent' ? 'Agent' : 'You'
                                    } · ${version.size}`}
                                </span>
                            </span>
                        </LemonButton>
                    </li>
                ))}
            </ol>
        </aside>
    )
}

function ArtifactsPane({ option, initial }: { option: Option; initial: Selection }): JSX.Element {
    const [selection, select] = useState<Selection>(initial)
    const [historyOpen, setHistoryOpen] = useState(option === 'history')
    const file = FILES[selection.fileIndex]
    const version = file.versions[selection.versionIndex]
    const isOld = selection.versionIndex > 0
    const props = { option, selection, select }
    return (
        <div className="flex min-h-0 flex-1">
            <FileNav {...props} />
            <section className="flex min-w-0 flex-1 flex-col">
                <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-primary px-3 py-1.5">
                    <span className="flex size-4 shrink-0 items-center text-secondary">
                        <KindIcon kind={file.kind} />
                    </span>
                    <span className="min-w-0 truncate font-semibold">{file.name}</span>
                    <span className="text-xs text-secondary">{`${version.size} · ${when(version)}`}</span>
                    <VersionControl {...props} />
                    <div className="ml-auto flex items-center gap-1">
                        {option === 'history' && file.versions.length > 1 && (
                            <LemonButton
                                size="small"
                                icon={<IconClockRewind />}
                                active={historyOpen}
                                onClick={() => setHistoryOpen(!historyOpen)}
                            >
                                {`${file.versions.length} versions`}
                            </LemonButton>
                        )}
                        <span className="px-1 text-xs text-secondary tabular-nums">{`${selection.fileIndex + 1} of ${FILES.length}`}</span>
                        <LemonButton size="small" icon={<IconChevronLeft />} tooltip="Previous file" />
                        <LemonButton size="small" icon={<IconChevronRight />} tooltip="Next file" />
                        <LemonButton size="small" icon={<IconDownload />} tooltip="Download this version" />
                    </div>
                </div>
                {isOld && (option === 'stepper' || option === 'menu') && (
                    <LemonBanner
                        type="info"
                        className="m-2 mb-0"
                        action={{ children: 'View latest', onClick: () => select({ ...selection, versionIndex: 0 }) }}
                    >
                        {`You're viewing ${versionLabel(file, selection.versionIndex).toLowerCase()}, from ${when(version)}.`}
                    </LemonBanner>
                )}
                <div className="flex min-h-0 flex-1">
                    <div
                        className={cn(
                            'min-h-0 min-w-0 flex-1 bg-surface-secondary',
                            file.kind === 'html' ? 'flex flex-col' : 'overflow-y-auto'
                        )}
                    >
                        <Preview file={file} version={version} />
                    </div>
                    {option === 'history' && historyOpen && file.versions.length > 1 && (
                        <HistoryPanel selection={selection} select={select} onClose={() => setHistoryOpen(false)} />
                    )}
                </div>
            </section>
        </div>
    )
}

const RUN = {
    id: 'run-trials',
    task: 'task-trials',
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
    artifacts: [],
    created_at: '2026-09-28T17:42:00Z',
    updated_at: '2026-09-28T18:19:00Z',
    completed_at: '2026-09-28T18:19:00Z',
} as TaskRun

const TASK = {
    id: 'task-trials',
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
    latest_run: RUN,
    created_at: '2026-09-28T17:42:00Z',
    updated_at: '2026-09-28T18:19:00Z',
    created_by: { id: 1, uuid: 'user-uuid', distinct_id: 'user-1', first_name: 'Ada', email: 'ada@example.com' },
} as Task

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

function MockPage({
    option,
    initial = { fileIndex: 0, versionIndex: 0 },
}: {
    option: Option
    initial?: Selection
}): JSX.Element {
    return (
        <TodayWebLayout>
            <TaskRunSceneShell
                task={TASK}
                selectedRun={RUN}
                titleActions={
                    <LemonButton type="secondary" size="small">
                        Open in PostHog Desktop
                    </LemonButton>
                }
                onArchive={() => {}}
                taskError={null}
                onRetry={() => {}}
                isMobile={false}
            >
                <LemonTabs
                    activeKey="artifacts"
                    onChange={() => {}}
                    barClassName="mb-0 px-4"
                    tabs={[
                        { key: 'conversation', label: 'Conversation' },
                        {
                            key: 'artifacts',
                            label: (
                                <span className="flex items-center gap-1.5">
                                    <span>Artifacts</span>
                                    <span className="text-secondary">{FILES.length}</span>
                                </span>
                            ),
                        },
                    ]}
                />
                <ArtifactsPane option={option} initial={initial} />
            </TaskRunSceneShell>
        </TodayWebLayout>
    )
}

const meta: Meta = {
    title: 'Mockups/Tasks/Artifact versions',
    // A design mockup for choosing a direction, not a product surface to snapshot.
    tags: ['test-skip'],
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/': { results: [], count: 0, next: null, previous: null },
                '/api/projects/:team_id/task_channels/': [],
                '/api/environments/:team_id/conversations/': { results: [], next: null },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-28 18:30:00',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.TASKS],
    },
}
export default meta

type Story = StoryObj<{}>

/** A version menu in the toolbar. The file list shows one row per file with a version count. */
export const OptionAVersionMenu: Story = { render: () => <MockPage option="menu" /> }

export const OptionAVersionMenuOlderVersion: Story = {
    render: () => <MockPage option="menu" initial={{ fileIndex: 0, versionIndex: 2 }} />,
}

/** Versions nest under their file in the file list, like a folder. */
export const OptionBNestedInFileList: Story = {
    render: () => <MockPage option="nested" initial={{ fileIndex: 0, versionIndex: 1 }} />,
}

/** A history panel opens next to the preview, with time and author for each version. */
export const OptionCHistoryPanel: Story = {
    render: () => <MockPage option="history" initial={{ fileIndex: 0, versionIndex: 1 }} />,
}

/** Older and newer arrows step through versions. A banner marks an older version. */
export const OptionDVersionStepper: Story = {
    render: () => <MockPage option="stepper" initial={{ fileIndex: 0, versionIndex: 1 }} />,
}
