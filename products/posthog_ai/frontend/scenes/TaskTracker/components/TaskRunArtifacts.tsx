import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import {
    IconChevronLeft,
    IconChevronRight,
    IconCode,
    IconDatabase,
    IconDocument,
    IconDownload,
    IconImage,
    IconLock,
} from '@posthog/icons'
import { LemonButton, LemonTable, LemonTabs, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { cn } from 'lib/utils/css-classes'

import { withStrictCsp } from '../artifactHtml'
import {
    ARTIFACT_KIND_LABEL,
    ArtifactPreviewKind,
    RunArtifact,
    TaskRunTab,
    artifactPreviewKind,
    formatArtifactSize,
    parseCsv,
} from '../taskRunArtifacts'
import { artifactDownloadUrl, taskRunArtifactsLogic } from '../taskRunArtifactsLogic'

const MAX_CSV_ROWS = 500

function KindIcon({ kind }: { kind: ArtifactPreviewKind }): JSX.Element {
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

/**
 * Agent-written HTML is untrusted. An empty `sandbox` gives the document an opaque origin with scripts,
 * forms, popups and top navigation all off, so it cannot reach the app's cookies, storage or DOM.
 */
function SandboxedHtmlFrame({ html, name }: { html: string; name: string }): JSX.Element {
    return (
        <iframe
            className="size-full border-0 bg-white"
            sandbox=""
            referrerPolicy="no-referrer"
            srcDoc={withStrictCsp(html)}
            title={`Preview of ${name}`}
        />
    )
}

function CsvPreview({ text }: { text: string }): JSX.Element {
    const { header, rows, truncated } = useMemo(() => {
        const [first = [], ...rest] = parseCsv(text)
        return { header: first, rows: rest.slice(0, MAX_CSV_ROWS), truncated: rest.length > MAX_CSV_ROWS }
    }, [text])
    return (
        <div className="flex flex-col gap-2 p-6">
            <LemonTable
                dataSource={rows.map((cells, index) => ({ index, cells }))}
                rowKey="index"
                size="small"
                columns={header.map((title, column) => ({
                    title,
                    key: String(column),
                    render: (_, row) => <span className="font-mono">{row.cells[column]}</span>,
                }))}
            />
            {truncated && (
                <span className="text-xs text-secondary">{`Showing the first ${MAX_CSV_ROWS} rows. Download the file to see all of them.`}</span>
            )}
        </div>
    )
}

function ArtifactPreview({ taskId }: { taskId: string }): JSX.Element | null {
    const { selectedArtifact, selectedKind, selectedText, selectedRun, currentProjectId, artifactTextLoading } =
        useValues(taskRunArtifactsLogic({ taskId }))
    const { ensureSelectedText, loadArtifactText } = useActions(taskRunArtifactsLogic({ taskId }))
    useEffect(() => {
        ensureSelectedText()
    }, [selectedArtifact?.id, selectedRun?.id, currentProjectId, ensureSelectedText])
    if (!selectedArtifact || !selectedKind) {
        return null
    }
    if (selectedKind === 'image') {
        const src = artifactDownloadUrl(currentProjectId, taskId, selectedArtifact)
        return (
            <div className="flex min-h-full items-center justify-center p-8">
                {src && (
                    <img
                        src={src}
                        alt={selectedArtifact.name}
                        className="max-w-full rounded border border-primary bg-white"
                    />
                )}
            </div>
        )
    }
    if (selectedKind === 'none') {
        return (
            <div className="flex min-h-full items-center justify-center p-8 text-sm text-secondary">
                This file type has no preview. Download it to open it.
            </div>
        )
    }
    if (!selectedText) {
        return (
            <div className="flex min-h-full items-center justify-center p-8">
                <Spinner className="text-2xl" />
            </div>
        )
    }
    if (selectedText.text === null) {
        return (
            <div className="flex min-h-full flex-col items-center justify-center gap-2 p-8 text-sm text-secondary">
                <span>{selectedText.error ?? 'This file did not load.'}</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    loading={artifactTextLoading}
                    onClick={() => loadArtifactText(selectedArtifact)}
                    data-attr="task-artifact-retry"
                >
                    Try again
                </LemonButton>
            </div>
        )
    }
    if (selectedKind === 'html') {
        return <SandboxedHtmlFrame html={selectedText.text} name={selectedArtifact.name} />
    }
    if (selectedKind === 'csv') {
        return <CsvPreview text={selectedText.text} />
    }
    if (selectedKind === 'markdown') {
        return (
            <div className="px-6 py-8">
                <article className="mx-auto max-w-3xl rounded-lg border border-primary bg-surface-primary px-10 py-8">
                    <LemonMarkdown disableImages="all">{selectedText.text}</LemonMarkdown>
                </article>
            </div>
        )
    }
    return <pre className="m-0 p-6 font-mono text-xs whitespace-pre-wrap break-words">{selectedText.text}</pre>
}

function ArtifactNav({ taskId }: { taskId: string }): JSX.Element {
    const { artifacts, selectedArtifact } = useValues(taskRunArtifactsLogic({ taskId }))
    const { selectArtifact } = useActions(taskRunArtifactsLogic({ taskId }))
    return (
        <nav
            className="hidden w-64 shrink-0 flex-col gap-px overflow-y-auto border-r border-primary p-2 @[52rem]/main-content:flex"
            aria-label="Artifacts"
        >
            <span className="py-1 pl-2 text-xs font-semibold text-secondary">{`Files ${artifacts.length}`}</span>
            {artifacts.map((artifact) => {
                const kind = artifactPreviewKind(artifact)
                return (
                    <LemonButton
                        key={artifact.id}
                        fullWidth
                        size="small"
                        active={artifact.id === selectedArtifact?.id}
                        icon={<KindIcon kind={kind} />}
                        onClick={() => artifact.id && selectArtifact(artifact.id)}
                        data-attr="task-artifact-nav-item"
                    >
                        <span className="flex min-w-0 flex-col py-0.5">
                            <span className="truncate">{artifact.name}</span>
                            <span className="text-xs font-normal text-secondary">
                                {`${ARTIFACT_KIND_LABEL[kind]} · ${formatArtifactSize(artifact.size)}`}
                            </span>
                        </span>
                    </LemonButton>
                )
            })}
        </nav>
    )
}

function ArtifactToolbar({ taskId, artifact }: { taskId: string; artifact: RunArtifact }): JSX.Element {
    const { artifacts, selectedIndex, currentProjectId } = useValues(taskRunArtifactsLogic({ taskId }))
    const { stepArtifact, downloadArtifact } = useActions(taskRunArtifactsLogic({ taskId }))
    const kind = artifactPreviewKind(artifact)
    const downloadUrl = artifactDownloadUrl(currentProjectId, taskId, artifact)
    const single = artifacts.length < 2
    return (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-primary px-3 py-1.5">
            <span className="flex size-4 shrink-0 items-center text-secondary">
                <KindIcon kind={kind} />
            </span>
            <span className="min-w-0 truncate font-semibold">{artifact.name}</span>
            <span className="text-xs text-secondary">
                {`${formatArtifactSize(artifact.size)} · ${dayjs(artifact.uploaded_at).fromNow()}`}
            </span>
            {kind === 'html' && (
                <Tooltip title="This page runs in a sandbox with scripts off. It cannot read your PostHog data, cookies or session.">
                    <LemonTag type="muted" icon={<IconLock />}>
                        Sandboxed
                    </LemonTag>
                </Tooltip>
            )}
            <div className="ml-auto flex items-center gap-1">
                <span className="px-1 text-xs text-secondary tabular-nums">{`${selectedIndex + 1} of ${artifacts.length}`}</span>
                <LemonButton
                    size="small"
                    icon={<IconChevronLeft />}
                    tooltip="Previous file"
                    disabledReason={single ? 'This is the only file' : undefined}
                    onClick={() => stepArtifact(-1)}
                />
                <LemonButton
                    size="small"
                    icon={<IconChevronRight />}
                    tooltip="Next file"
                    disabledReason={single ? 'This is the only file' : undefined}
                    onClick={() => stepArtifact(1)}
                />
                <LemonButton
                    size="small"
                    icon={<IconDownload />}
                    tooltip="Download"
                    to={downloadUrl ?? undefined}
                    disableClientSideRouting
                    disabledReason={downloadUrl ? undefined : 'The file is not ready yet'}
                    onClick={() => downloadArtifact(artifact)}
                    data-attr="task-artifact-download"
                />
            </div>
        </div>
    )
}

function ArtifactsWorkspace({ taskId }: { taskId: string }): JSX.Element {
    const { artifacts, selectedArtifact, selectedKind } = useValues(taskRunArtifactsLogic({ taskId }))
    const { setActiveTab } = useActions(taskRunArtifactsLogic({ taskId }))
    if (artifacts.length === 0 || !selectedArtifact) {
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
                <LemonButton type="secondary" size="small" onClick={() => setActiveTab('conversation')}>
                    Go to the conversation
                </LemonButton>
            </div>
        )
    }
    return (
        <div className="flex min-h-0 flex-1">
            <ArtifactNav taskId={taskId} />
            <section className="flex min-w-0 flex-1 flex-col">
                <ArtifactToolbar taskId={taskId} artifact={selectedArtifact} />
                <div
                    className={cn(
                        'min-h-0 flex-1 bg-surface-secondary',
                        selectedKind === 'html' ? 'flex flex-col' : 'overflow-y-auto'
                    )}
                >
                    <ArtifactPreview taskId={taskId} />
                </div>
            </section>
        </div>
    )
}

/** Conversation and Artifacts tabs for a task run. The caller renders the thread as `conversation`. */
export function TaskRunTabs({ taskId, conversation }: { taskId: string; conversation: JSX.Element }): JSX.Element {
    const { activeTab, artifacts } = useValues(taskRunArtifactsLogic({ taskId }))
    const { setActiveTab } = useActions(taskRunArtifactsLogic({ taskId }))
    return (
        <>
            <LemonTabs<TaskRunTab>
                activeKey={activeTab}
                onChange={setActiveTab}
                barClassName="mb-0 px-4"
                tabs={[
                    { key: 'conversation', label: 'Conversation', 'data-attr': 'task-run-tab-conversation' },
                    {
                        key: 'artifacts',
                        label: (
                            <span className="flex items-center gap-1.5">
                                <span>Artifacts</span>
                                {artifacts.length > 0 && <span className="text-secondary">{artifacts.length}</span>}
                            </span>
                        ),
                        'data-attr': 'task-run-tab-artifacts',
                    },
                ]}
            />
            {activeTab === 'conversation' ? conversation : <ArtifactsWorkspace taskId={taskId} />}
        </>
    )
}
