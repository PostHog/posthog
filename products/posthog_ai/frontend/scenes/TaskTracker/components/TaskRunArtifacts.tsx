import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import {
    IconCheck,
    IconChevronLeft,
    IconChevronRight,
    IconCode,
    IconCollapse45,
    IconCopy,
    IconDatabase,
    IconDocument,
    IconDownload,
    IconExpand45,
    IconImage,
    IconLock,
} from '@posthog/icons'
import {
    Badge,
    Button,
    Dialog,
    DialogContent,
    DialogTitle,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    SkeletonText,
    Spinner,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
    cn,
} from '@posthog/quill-primitives'

import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { withStrictCsp } from '../artifactHtml'
import {
    ArtifactFile,
    ArtifactPreviewKind,
    RunArtifact,
    TaskRunTab,
    artifactPreviewKind,
    formatArtifactSize,
    isTextPreview,
    parseCsv,
} from '../taskRunArtifacts'
import { artifactDownloadUrl, taskRunArtifactsLogic } from '../taskRunArtifactsLogic'
import { ArtifactImageViewer } from './ArtifactImageViewer'

const MAX_CSV_ROWS = 500

type PreviewMode = 'rendered' | 'source'

function KindIcon({ kind, className }: { kind: ArtifactPreviewKind; className?: string }): JSX.Element {
    const Icon =
        kind === 'html' ? IconCode : kind === 'image' ? IconImage : kind === 'csv' ? IconDatabase : IconDocument
    return <Icon className={className} />
}

function IconAction({
    label,
    onClick,
    href,
    disabledReason,
    children,
    dataAttr,
}: {
    label: string
    onClick?: () => void
    href?: string
    disabledReason?: string
    children: JSX.Element
    dataAttr: string
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon"
                        aria-label={label}
                        disabled={!!disabledReason}
                        onClick={onClick}
                        data-attr={dataAttr}
                        // eslint-disable-next-line react/forbid-elements
                        render={href && !disabledReason ? <a href={href} download /> : undefined}
                    />
                }
            >
                {children}
            </TooltipTrigger>
            <TooltipContent>{disabledReason ?? label}</TooltipContent>
        </Tooltip>
    )
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
            <div className="overflow-hidden rounded-md border border-border bg-card text-card-foreground">
                <Table>
                    <TableHeader>
                        <TableRow>
                            {header.map((title, column) => (
                                <TableHead key={column}>{title}</TableHead>
                            ))}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {rows.map((cells, index) => (
                            <TableRow key={index}>
                                {header.map((_, column) => (
                                    <TableCell key={column} className="font-mono tabular-nums">
                                        {cells[column]}
                                    </TableCell>
                                ))}
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
            {truncated && (
                <Text size="xs" variant="muted">
                    {`Showing the first ${MAX_CSV_ROWS} rows. Download the file to see all of them.`}
                </Text>
            )}
        </div>
    )
}

function SourceView({ text }: { text: string }): JSX.Element {
    return (
        <pre className="m-0 min-h-full p-6 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words text-foreground">
            {text}
        </pre>
    )
}

function TextLoading(): JSX.Element {
    return (
        <div className="px-6 py-8">
            <div className="mx-auto flex max-w-3xl flex-col gap-4 rounded-lg border border-border bg-card px-10 py-8">
                <SkeletonText lines={1} />
                <SkeletonText lines={5} />
            </div>
        </div>
    )
}

function ArtifactPreview({ taskId, mode }: { taskId: string; mode: PreviewMode }): JSX.Element | null {
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
        return src ? <ArtifactImageViewer key={selectedArtifact.id} src={src} alt={selectedArtifact.name} /> : null
    }
    if (selectedKind === 'none') {
        return (
            <Empty className="h-full">
                <EmptyHeader>
                    <EmptyTitle>No preview for this file</EmptyTitle>
                    <EmptyDescription>Download it to open it on your computer.</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }
    if (!selectedText) {
        return selectedKind === 'html' ? (
            <div className="flex h-full items-center justify-center">
                <Spinner />
            </div>
        ) : (
            <TextLoading />
        )
    }
    if (selectedText.text === null) {
        return (
            <Empty className="h-full">
                <EmptyHeader>
                    <EmptyTitle>This file didn't load</EmptyTitle>
                    <EmptyDescription>{selectedText.error ?? 'Check your connection and try again.'}</EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button
                        variant="outline"
                        loading={artifactTextLoading}
                        onClick={() => loadArtifactText(selectedArtifact)}
                        data-attr="task-artifact-retry"
                    >
                        Try again
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }
    if (mode === 'source') {
        return <SourceView text={selectedText.text} />
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
                <article className="mx-auto max-w-3xl rounded-lg border border-border bg-card px-10 py-8 text-card-foreground">
                    <LemonMarkdown disableImages="all">{selectedText.text}</LemonMarkdown>
                </article>
            </div>
        )
    }
    return <SourceView text={selectedText.text} />
}

function fileMeta(file: ArtifactFile): string {
    const age = dayjs(file.latest.uploaded_at).fromNow()
    return file.versions.length > 1
        ? `${file.versions.length} versions · ${age}`
        : `${formatArtifactSize(file.latest.size)} · ${age}`
}

function ArtifactNav({ taskId }: { taskId: string }): JSX.Element {
    const { files, selectedFile } = useValues(taskRunArtifactsLogic({ taskId }))
    const { selectArtifact } = useActions(taskRunArtifactsLogic({ taskId }))
    return (
        <aside className="hidden w-64 shrink-0 flex-col border-r border-border @[52rem]/main-content:flex">
            <div className="flex h-10 shrink-0 items-center gap-1.5 border-b border-border px-3">
                <Text size="xs" weight="medium" variant="muted" render={<span />}>
                    Files
                </Text>
                <Text size="xs" variant="muted" render={<span />} className="tabular-nums">
                    {files.length}
                </Text>
            </div>
            <div
                role="listbox"
                aria-label="Files"
                className="flex min-h-0 flex-1 flex-col gap-px overflow-y-auto p-1.5"
            >
                {files.map((file) => {
                    const selected = file.name === selectedFile?.name
                    return (
                        <Item
                            key={file.name}
                            size="xs"
                            role="option"
                            aria-selected={selected}
                            className={cn(
                                'w-full cursor-pointer rounded-md border-transparent text-left hover:bg-fill-hover',
                                selected && 'bg-fill-selected hover:bg-fill-selected'
                            )}
                            // eslint-disable-next-line react/forbid-elements
                            render={<button type="button" />}
                            onClick={() => selectArtifact(file.name)}
                            data-attr="task-artifact-nav-item"
                        >
                            <ItemMedia>
                                <KindIcon
                                    kind={artifactPreviewKind(file.latest)}
                                    className="size-4 text-muted-foreground"
                                />
                            </ItemMedia>
                            <ItemContent className="min-w-0">
                                <ItemTitle className="w-full truncate">{file.name}</ItemTitle>
                                <ItemDescription className="truncate">{fileMeta(file)}</ItemDescription>
                            </ItemContent>
                        </Item>
                    )
                })}
            </div>
        </aside>
    )
}

function VersionSelect({ taskId, file }: { taskId: string; file: ArtifactFile }): JSX.Element {
    const { selectedVersion } = useValues(taskRunArtifactsLogic({ taskId }))
    const { selectVersion } = useActions(taskRunArtifactsLogic({ taskId }))
    const total = file.versions.length
    const items = file.versions.map((version, index) => ({
        value: version.id ?? '',
        label: `Version ${total - index}`,
    }))
    return (
        <Select
            items={items}
            value={selectedVersion?.id ?? ''}
            // Picking the newest follows the latest, so the next upload shows without another pick.
            onValueChange={(id: string | null) => selectVersion(!id || id === file.latest.id ? null : id)}
        >
            <SelectTrigger aria-label="Version" data-attr="task-artifact-version-select" className="shrink-0">
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                {file.versions.map((version, index) => (
                    <SelectItem key={version.id} value={version.id ?? ''}>
                        <span className="flex w-52 items-center gap-2">
                            <span>{`Version ${total - index}`}</span>
                            {index === 0 && <Badge variant="success">Latest</Badge>}
                            <Text
                                size="xs"
                                variant="muted"
                                render={<span />}
                                className="ml-auto tabular-nums"
                                title={dayjs(version.uploaded_at).format('MMM D, YYYY HH:mm')}
                            >
                                {dayjs(version.uploaded_at).fromNow()}
                            </Text>
                        </span>
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}

function OlderVersionNotice({ taskId }: { taskId: string }): JSX.Element | null {
    const { selectedFile, selectedVersion, selectedVersionIndex } = useValues(taskRunArtifactsLogic({ taskId }))
    const { selectVersion } = useActions(taskRunArtifactsLogic({ taskId }))
    if (!selectedFile || !selectedVersion || selectedVersionIndex === 0) {
        return null
    }
    const total = selectedFile.versions.length
    return (
        <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border bg-info px-3 text-info-foreground">
            <Text size="xs" render={<span />} className="min-w-0 truncate text-info-foreground">
                {`You're viewing version ${total - selectedVersionIndex} of ${total}, from ${dayjs(
                    selectedVersion.uploaded_at
                ).fromNow()}.`}
            </Text>
            <Button
                size="xs"
                variant="outline"
                className="ml-auto shrink-0"
                onClick={() => selectVersion(null)}
                data-attr="task-artifact-view-latest"
            >
                View latest
            </Button>
        </div>
    )
}

function CopySourceAction({ text }: { text: string | null }): JSX.Element {
    const [copied, setCopied] = useState(false)
    useEffect(() => {
        if (!copied) {
            return
        }
        const timeout = window.setTimeout(() => setCopied(false), 2000)
        return () => window.clearTimeout(timeout)
    }, [copied])
    return (
        <IconAction
            label={copied ? 'Copied' : 'Copy source'}
            disabledReason={text === null ? 'The file has not loaded yet' : undefined}
            onClick={() => {
                if (text !== null) {
                    void navigator.clipboard.writeText(text).then(() => setCopied(true))
                }
            }}
            dataAttr="task-artifact-copy"
        >
            {copied ? <IconCheck className="size-4" /> : <IconCopy className="size-4" />}
        </IconAction>
    )
}

function ArtifactToolbar({
    taskId,
    artifact,
    mode,
    onModeChange,
    expanded,
    onExpandedChange,
}: {
    taskId: string
    artifact: RunArtifact
    mode: PreviewMode
    onModeChange: (mode: PreviewMode) => void
    expanded: boolean
    onExpandedChange: (expanded: boolean) => void
}): JSX.Element {
    const { files, selectedFile, selectedIndex, selectedText, currentProjectId } = useValues(
        taskRunArtifactsLogic({ taskId })
    )
    const { stepArtifact, downloadArtifact } = useActions(taskRunArtifactsLogic({ taskId }))
    const kind = artifactPreviewKind(artifact)
    const downloadUrl = artifactDownloadUrl(currentProjectId, taskId, artifact)
    const single = files.length < 2
    const versioned = !!selectedFile && selectedFile.versions.length > 1
    // Plain text already shows its source, so only these kinds get a view switch.
    const hasRenderedForm = kind === 'markdown' || kind === 'html' || kind === 'csv'
    return (
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-background px-3">
            <KindIcon kind={kind} className="size-4 shrink-0 text-muted-foreground" />
            {/* The name truncates and the meta hides on narrow panes, so the tooltip carries both in full. */}
            <Tooltip>
                <TooltipTrigger render={<span className="flex min-w-0 items-baseline gap-2" />}>
                    <Text size="sm" weight="medium" render={<span />} className="min-w-0 truncate">
                        {artifact.name}
                    </Text>
                    <Text
                        size="xs"
                        variant="muted"
                        render={<span />}
                        className="hidden shrink-0 tabular-nums @[40rem]/main-content:inline"
                    >
                        {`${formatArtifactSize(artifact.size)} · ${dayjs(artifact.uploaded_at).fromNow()}`}
                    </Text>
                </TooltipTrigger>
                <TooltipContent>
                    {`${artifact.name} · ${formatArtifactSize(artifact.size)} · ${dayjs(artifact.uploaded_at).format('MMM D, YYYY HH:mm')}`}
                </TooltipContent>
            </Tooltip>
            {versioned && selectedFile && <VersionSelect taskId={taskId} file={selectedFile} />}
            {kind === 'html' && (
                <Tooltip>
                    <TooltipTrigger render={<Badge className="shrink-0" />}>
                        <IconLock />
                        Sandboxed
                    </TooltipTrigger>
                    <TooltipContent>
                        This page runs with scripts off and no network. It can't read your PostHog data, cookies or
                        session.
                    </TooltipContent>
                </Tooltip>
            )}
            <div className="ml-auto flex shrink-0 items-center gap-1">
                {hasRenderedForm && (
                    <ToggleGroup
                        variant="outline"
                        value={[mode]}
                        onValueChange={(value: string[]) => value[0] && onModeChange(value[0] as PreviewMode)}
                        aria-label="View"
                        className="mr-1"
                    >
                        <ToggleGroupItem value="rendered" data-attr="task-artifact-view-rendered">
                            Preview
                        </ToggleGroupItem>
                        <ToggleGroupItem value="source" data-attr="task-artifact-view-source">
                            Source
                        </ToggleGroupItem>
                    </ToggleGroup>
                )}
                {isTextPreview(kind) && <CopySourceAction text={selectedText?.text ?? null} />}
                {/* The file list replaces these once there is room for it. */}
                <div className="flex items-center gap-1 @[52rem]/main-content:hidden">
                    <Text size="xs" variant="muted" render={<span />} className="px-1 tabular-nums">
                        {`${selectedIndex + 1} of ${files.length}`}
                    </Text>
                    <IconAction
                        label="Previous file"
                        disabledReason={single ? 'This is the only file' : undefined}
                        onClick={() => stepArtifact(-1)}
                        dataAttr="task-artifact-previous"
                    >
                        <IconChevronLeft className="size-4" />
                    </IconAction>
                    <IconAction
                        label="Next file"
                        disabledReason={single ? 'This is the only file' : undefined}
                        onClick={() => stepArtifact(1)}
                        dataAttr="task-artifact-next"
                    >
                        <IconChevronRight className="size-4" />
                    </IconAction>
                </div>
                <IconAction
                    label={versioned ? 'Download this version' : 'Download'}
                    href={downloadUrl ?? undefined}
                    disabledReason={downloadUrl ? undefined : 'The file is not ready yet'}
                    onClick={() => downloadArtifact(artifact)}
                    dataAttr="task-artifact-download"
                >
                    <IconDownload className="size-4" />
                </IconAction>
                <IconAction
                    label={expanded ? 'Exit full page' : 'Open full page'}
                    onClick={() => onExpandedChange(!expanded)}
                    dataAttr={expanded ? 'task-artifact-collapse' : 'task-artifact-expand'}
                >
                    {expanded ? <IconCollapse45 className="size-4" /> : <IconExpand45 className="size-4" />}
                </IconAction>
            </div>
        </div>
    )
}

function PreviewSurface({ taskId, mode }: { taskId: string; mode: PreviewMode }): JSX.Element {
    const { selectedKind } = useValues(taskRunArtifactsLogic({ taskId }))
    const fills = mode === 'rendered' && (selectedKind === 'html' || selectedKind === 'image')
    return (
        <div className={cn('min-h-0 flex-1 bg-surface-tertiary', fills ? 'flex flex-col' : 'overflow-y-auto')}>
            <ArtifactPreview taskId={taskId} mode={mode} />
        </div>
    )
}

function ArtifactsWorkspace({ taskId }: { taskId: string }): JSX.Element {
    const { files, selectedArtifact } = useValues(taskRunArtifactsLogic({ taskId }))
    const { setActiveTab } = useActions(taskRunArtifactsLogic({ taskId }))
    const [mode, setMode] = useState<PreviewMode>('rendered')
    const [expanded, setExpanded] = useState(false)
    // A new file opens in its rendered form, whatever the last file showed.
    useEffect(() => setMode('rendered'), [selectedArtifact?.id])

    if (files.length === 0 || !selectedArtifact) {
        return (
            <Empty className="flex-1">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconDocument />
                    </EmptyMedia>
                    <EmptyTitle>No artifacts yet</EmptyTitle>
                    <EmptyDescription>
                        Files that the agent writes in this task show here. Ask it for a report, a chart, a CSV or an
                        HTML page.
                    </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button variant="outline" onClick={() => setActiveTab('conversation')}>
                        Go to the conversation
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }
    const toolbar = (
        <ArtifactToolbar
            taskId={taskId}
            artifact={selectedArtifact}
            mode={mode}
            onModeChange={setMode}
            expanded={expanded}
            onExpandedChange={setExpanded}
        />
    )
    return (
        <div className="flex min-h-0 flex-1">
            <ArtifactNav taskId={taskId} />
            <section className="flex min-w-0 flex-1 flex-col">
                {toolbar}
                {!expanded && (
                    <>
                        <OlderVersionNotice taskId={taskId} />
                        <PreviewSurface taskId={taskId} mode={mode} />
                    </>
                )}
            </section>
            <Dialog open={expanded} onOpenChange={setExpanded}>
                <DialogContent size="full" showCloseButton={false} className="flex h-full flex-col gap-0 p-0">
                    <DialogTitle className="sr-only">{selectedArtifact.name}</DialogTitle>
                    {/* The toolbar hides parts by container width, so the dialog gets its own container. */}
                    <div className="@container/main-content flex min-h-0 flex-1 flex-col">
                        {toolbar}
                        <OlderVersionNotice taskId={taskId} />
                        <PreviewSurface taskId={taskId} mode={mode} />
                    </div>
                </DialogContent>
            </Dialog>
        </div>
    )
}

/** Conversation and Artifacts tabs for a task run. The caller renders the thread as `conversation`. */
export function TaskRunTabs({ taskId, conversation }: { taskId: string; conversation: JSX.Element }): JSX.Element {
    const { activeTab, files } = useValues(taskRunArtifactsLogic({ taskId }))
    const { setActiveTab } = useActions(taskRunArtifactsLogic({ taskId }))
    return (
        <TooltipProvider>
            <Tabs
                value={activeTab}
                onValueChange={(tab: TaskRunTab) => setActiveTab(tab)}
                className="flex min-h-0 flex-1 flex-col gap-0"
                data-quill
            >
                <div className="shrink-0 border-b border-border px-2">
                    <TabsList variant="line" aria-label="Task views" className="p-0">
                        <TabsTrigger value="conversation" data-attr="task-run-tab-conversation">
                            Conversation
                        </TabsTrigger>
                        <TabsTrigger value="artifacts" data-attr="task-run-tab-artifacts">
                            Artifacts
                            {files.length > 0 && (
                                <Text size="xs" variant="muted" render={<span />} className="tabular-nums">
                                    {files.length}
                                </Text>
                            )}
                        </TabsTrigger>
                    </TabsList>
                </div>
                <TabsContent value="conversation" className="flex min-h-0 flex-1 flex-col">
                    {conversation}
                </TabsContent>
                <TabsContent value="artifacts" className="flex min-h-0 flex-1 flex-col">
                    <ArtifactsWorkspace taskId={taskId} />
                </TabsContent>
            </Tabs>
        </TooltipProvider>
    )
}
