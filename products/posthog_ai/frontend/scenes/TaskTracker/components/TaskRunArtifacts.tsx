import { useActions, useValues } from 'kea'
import { KeyboardEvent, useEffect, useMemo, useState } from 'react'

import {
    IconCheck,
    IconChevronLeft,
    IconChevronRight,
    IconCollapse45,
    IconCopy,
    IconDocument,
    IconDownload,
    IconEllipsis,
    IconExpand45,
    IconExternal,
    IconLock,
    IconPencil,
    IconShare,
    IconHide,
} from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
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
    Kbd,
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
    toast,
} from '@posthog/quill-primitives'

import { objectKindLink } from 'lib/components/AgentObjectTags/rewriteAgentObjectTags'
import { dayjs } from 'lib/dayjs'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { SHEET_PARTS } from '~/layout/today/todayMenuParts'
import { TodaySheetMenu } from '~/layout/today/TodaySheetMenu'

import { isCommentableArtifact, regionAnchorAt, supportsSelectionComments } from '../artifactComments'
import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import {
    ArtifactFile,
    ArtifactPreviewKind,
    RunArtifact,
    TaskRunTab,
    artifactPreviewKind,
    formatArtifactSize,
    hasFullPageView,
    hasLivingContent,
    isTextPreview,
    listboxKeyTarget,
    parseCsv,
    LIVING_ADAPTER_LABEL,
    objectPageUrl,
    postHogObjectRef,
} from '../taskRunArtifacts'
import { FullPageSource, artifactDownloadUrl, taskRunArtifactsLogic } from '../taskRunArtifactsLogic'
import { ArtifactCommentActions } from './ArtifactCommentActions'
import { ArtifactCommentsButton, ArtifactCommentsPage } from './ArtifactCommentsPage'
import { ArtifactEditor } from './ArtifactEditor'
import { ArtifactEditToolbar } from './ArtifactEditToolbar'
import { ArtifactIcon } from './ArtifactIcon'
import { ArtifactImagePins } from './ArtifactImagePins'
import { ArtifactImageViewer } from './ArtifactImageViewer'
import { ArtifactObjectEmbed } from './ArtifactObjectEmbed'
import { ArtifactTextAnnotations } from './ArtifactTextAnnotations'

const MAX_CSV_ROWS = 500

type PreviewMode = 'rendered' | 'source'

const FULL_PAGE_KEY = 'f'

/** The replay player uses F for its own full screen, so a replay gets no full page shortcut. */
function hasFullPageShortcut(artifact: RunArtifact): boolean {
    return postHogObjectRef(artifact)?.objectKind !== 'replay'
}

/** The comments logic for an artifact version, or null when the artifact takes no comments. */
function commentLogicProps(
    taskId: string,
    artifact: RunArtifact | null,
    kind: ArtifactPreviewKind | null
): TaskArtifactCommentsLogicProps | null {
    return isCommentableArtifact(artifact) && kind ? { taskId, artifactId: artifact.id, kind } : null
}

/** Size for a file, the object kind for a cited PostHog object, where the agent sent a living document. */
function artifactDetail(artifact: RunArtifact): string {
    if (artifact.living) {
        return LIVING_ADAPTER_LABEL[artifact.living.adapter] ?? 'Document'
    }
    const ref = postHogObjectRef(artifact)
    return ref ? objectKindLink(ref.objectKind, ref.objectId, '').kind.kindLabel : formatArtifactSize(artifact.size)
}

function IconAction({
    label,
    onClick,
    href,
    to,
    disabledReason,
    loading,
    shortcut,
    children,
    dataAttr,
}: {
    label: string
    onClick?: () => void
    /** A file to download. */
    href?: string
    /** An app page to open. */
    to?: string
    disabledReason?: string
    loading?: boolean
    /** The key that does the same action, shown in the tooltip. */
    shortcut?: string
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
                        loading={loading}
                        onClick={onClick}
                        data-attr={dataAttr}
                        // A link renders as `<a>`, so Base UI must not expect a native button.
                        nativeButton={disabledReason ? true : !href && !to}
                        render={
                            disabledReason ? undefined : href ? (
                                // eslint-disable-next-line react/forbid-elements
                                <a href={href} download />
                            ) : to ? (
                                <LinkPrimitive to={to} />
                            ) : undefined
                        }
                    />
                }
            >
                {children}
            </TooltipTrigger>
            <TooltipContent>
                {disabledReason ?? label}
                {shortcut && !disabledReason && <Kbd>{shortcut}</Kbd>}
            </TooltipContent>
        </Tooltip>
    )
}

function SandboxedHtmlFrame({ url, name }: { url: string; name: string }): JSX.Element {
    return (
        <iframe
            className="size-full border-0 bg-white"
            sandbox="allow-scripts"
            referrerPolicy="no-referrer"
            src={url}
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

function MarkdownArticle({ text }: { text: string }): JSX.Element {
    return (
        <div className="px-6 py-8">
            <article className="mx-auto max-w-3xl rounded-lg border border-border bg-card px-10 py-8 text-card-foreground">
                <LemonMarkdown disableImages="all">{text}</LemonMarkdown>
            </article>
        </div>
    )
}

function CommentableImage({
    logicProps,
    src,
    alt,
}: {
    logicProps: TaskArtifactCommentsLogicProps
    src: string
    alt: string
}): JSX.Element {
    const { pinMode } = useValues(taskArtifactCommentsLogic(logicProps))
    const { setPendingAnchor } = useActions(taskArtifactCommentsLogic(logicProps))
    return (
        <ArtifactImageViewer
            src={src}
            alt={alt}
            overlay={<ArtifactImagePins logicProps={logicProps} />}
            onPlace={pinMode ? (x, y) => setPendingAnchor(regionAnchorAt(x, y), null) : undefined}
        />
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

function VideoPreview({ taskId, name }: { taskId: string; name: string }): JSX.Element {
    const { selectedArtifact, selectedMedia, artifactMediaLoading, currentProjectId } = useValues(
        taskRunArtifactsLogic({ taskId })
    )
    const { loadArtifactMedia } = useActions(taskRunArtifactsLogic({ taskId }))
    // A stored living version streams from the app origin, which the media-src policy allows.
    const livingSrc = selectedArtifact?.living ? artifactDownloadUrl(currentProjectId, taskId, selectedArtifact) : null
    if (livingSrc) {
        return <VideoPlayer key={livingSrc} src={livingSrc} name={name} />
    }
    if (!selectedMedia) {
        return (
            <div className="flex h-full items-center justify-center">
                <Spinner />
            </div>
        )
    }
    if (!selectedMedia.url) {
        return (
            <Empty className="h-full">
                <EmptyHeader>
                    <EmptyTitle>This video can't play here</EmptyTitle>
                    <EmptyDescription>{selectedMedia.error}</EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button
                        variant="outline"
                        loading={artifactMediaLoading}
                        onClick={() => selectedArtifact && loadArtifactMedia(selectedArtifact)}
                        data-attr="task-artifact-retry"
                    >
                        Try again
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }
    return <VideoPlayer key={selectedMedia.artifactId} src={selectedMedia.url} name={name} />
}

function VideoPlayer({ src, name }: { src: string; name: string }): JSX.Element {
    return (
        <div className="flex h-full items-center justify-center p-6">
            <video
                src={src}
                controls
                preload="metadata"
                aria-label={name}
                className="max-h-full max-w-full rounded-sm border border-border bg-black"
            />
        </div>
    )
}

/** Sentence case for a button: "Insight" reads "Open insight", "LLM trace" keeps its acronym. */
function lowerFirst(label: string): string {
    return /^[A-Z][a-z]/.test(label) ? label[0].toLowerCase() + label.slice(1) : label
}

function ReferencePreview({ taskId, artifact }: { taskId: string; artifact: RunArtifact }): JSX.Element | null {
    const { currentProjectId } = useValues(taskRunArtifactsLogic({ taskId }))
    const ref = postHogObjectRef(artifact)
    if (!ref || currentProjectId === null) {
        return null
    }
    const url = objectPageUrl(ref, currentProjectId)
    if (url) {
        // Keyed by the page, so the loading state starts over whenever the frame shows a different page.
        return <ArtifactObjectEmbed key={url} url={url} title={artifact.name} />
    }
    const { kind } = objectKindLink(ref.objectKind, ref.objectId, `/project/${currentProjectId}`)
    return (
        <div className="flex h-full items-center justify-center p-6">
            <Card className="w-full max-w-sm">
                <CardHeader>
                    <div className="flex min-w-0 items-start gap-3">
                        <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground">
                            <ArtifactIcon artifact={artifact} className="size-4" />
                        </span>
                        <div className="flex min-w-0 flex-col gap-1">
                            <CardTitle className="truncate">{artifact.name}</CardTitle>
                            <CardDescription>
                                {/* "Feature flag in Feature flags" repeats itself, so a kind named like its product shows the product alone. */}
                                {kind.source.toLowerCase().startsWith(kind.kindLabel.toLowerCase())
                                    ? kind.source
                                    : `${kind.kindLabel} in ${kind.source}`}
                            </CardDescription>
                        </div>
                    </div>
                </CardHeader>
                <CardContent>
                    <Text size="xs" variant="muted">
                        This object has no page to open.
                    </Text>
                </CardContent>
            </Card>
        </div>
    )
}

function ArtifactPreview({ taskId, mode }: { taskId: string; mode: PreviewMode }): JSX.Element | null {
    const {
        selectedArtifact,
        selectedKind,
        selectedText,
        selectedRun,
        currentProjectId,
        artifactTextLoading,
        todayPhone,
        htmlPreview,
        htmlPreviewLoading,
    } = useValues(taskRunArtifactsLogic({ taskId }))
    const { ensureSelectedText, loadArtifactText, loadHtmlPreview } = useActions(taskRunArtifactsLogic({ taskId }))
    useEffect(() => {
        ensureSelectedText()
    }, [selectedArtifact?.id, selectedRun?.id, currentProjectId, mode, ensureSelectedText])
    if (!selectedArtifact || !selectedKind) {
        return null
    }
    const comments = commentLogicProps(taskId, selectedArtifact, selectedKind)
    if (selectedKind === 'image') {
        const src = artifactDownloadUrl(currentProjectId, taskId, selectedArtifact)
        if (!src) {
            return null
        }
        return comments ? (
            <CommentableImage key={selectedArtifact.id} logicProps={comments} src={src} alt={selectedArtifact.name} />
        ) : (
            <ArtifactImageViewer key={selectedArtifact.id} src={src} alt={selectedArtifact.name} />
        )
    }
    if (selectedKind === 'reference') {
        return <ReferencePreview taskId={taskId} artifact={selectedArtifact} />
    }
    if (selectedKind === 'video') {
        return <VideoPreview taskId={taskId} name={selectedArtifact.name} />
    }
    if (selectedArtifact.living && !hasLivingContent(selectedArtifact.living)) {
        return (
            <Empty className="h-full">
                <EmptyHeader>
                    <EmptyTitle>No preview for this document</EmptyTitle>
                    <EmptyDescription>
                        {selectedArtifact.living.adapter.startsWith('slack_')
                            ? "PostHog can't show this version here. Open the Slack thread the agent replied in to see it."
                            : "PostHog can't show this version here. Open it where the agent saved it."}
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
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
    if (selectedKind === 'html' && mode === 'rendered') {
        if (!htmlPreview || htmlPreview.artifactId !== selectedArtifact.id || htmlPreviewLoading) {
            return (
                <div className="flex h-full items-center justify-center">
                    <Spinner />
                </div>
            )
        }
        if (!htmlPreview.url) {
            return (
                <Empty className="h-full">
                    <EmptyHeader>
                        <EmptyTitle>This HTML preview didn't load</EmptyTitle>
                        <EmptyDescription>{htmlPreview.error}</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            loading={htmlPreviewLoading}
                            onClick={() => loadHtmlPreview(selectedArtifact)}
                            data-attr="task-artifact-retry-preview"
                        >
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        return <SandboxedHtmlFrame key={selectedArtifact.id} url={htmlPreview.url} name={selectedArtifact.name} />
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
    // Desktop counts a markdown quote in the rendered page, not in the source, so only the page takes selections.
    if (comments && supportsSelectionComments(selectedKind) && (mode === 'rendered' || selectedKind === 'text')) {
        return (
            <ArtifactTextAnnotations key={selectedArtifact.id} logicProps={comments} selectable={!todayPhone}>
                {selectedKind === 'markdown' ? (
                    <MarkdownArticle text={selectedText.text} />
                ) : (
                    <SourceView text={selectedText.text} />
                )}
            </ArtifactTextAnnotations>
        )
    }
    if (mode === 'source') {
        return <SourceView text={selectedText.text} />
    }
    if (selectedKind === 'csv') {
        return <CsvPreview text={selectedText.text} />
    }
    if (selectedKind === 'markdown') {
        return <MarkdownArticle text={selectedText.text} />
    }
    return <SourceView text={selectedText.text} />
}

function fileMeta(file: ArtifactFile): string {
    const age = dayjs(file.latest.uploaded_at).fromNow()
    return file.versions.length > 1
        ? `${file.versions.length} versions · ${age}`
        : `${artifactDetail(file.latest)} · ${age}`
}

function ArtifactFileList({ taskId, size, label }: { taskId: string; size: 'xs' | 'sm'; label: string }): JSX.Element {
    const { files, selectedFile, isEditing, todayPhone } = useValues(taskRunArtifactsLogic({ taskId }))
    const { selectArtifact } = useActions(taskRunArtifactsLogic({ taskId }))
    // Cited PostHog objects sit under their own label, after the files.
    const objects = files.filter((file) => !!postHogObjectRef(file.latest))
    const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
        const target = event.target as HTMLElement
        if (event.altKey || event.ctrlKey || event.metaKey || target.getAttribute('role') !== 'option') {
            return
        }
        // The rendered rows give the order, so the keys follow the list as it reads, across its groups.
        const options = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="option"]'))
        const next = options[listboxKeyTarget(event.key, options.indexOf(target), options.length) ?? -1]
        if (!next?.dataset.fileKey) {
            return
        }
        event.preventDefault()
        selectArtifact(next.dataset.fileKey, 'keyboard')
        next.focus()
    }
    const renderRow = (file: ArtifactFile): JSX.Element => {
        // The phone list opens a file, so no row shows as the open one.
        const selected = !todayPhone && file.key === selectedFile?.key
        return (
            <Item
                key={file.key}
                size={size}
                aria-selected={selected}
                // Roving tabindex: Tab enters the list on the open file, and the arrow keys move from there.
                tabIndex={selected || (todayPhone && file === files[0]) ? 0 : -1}
                data-file-key={file.key}
                className={cn(
                    'w-full cursor-pointer rounded-md border-transparent text-left hover:bg-fill-hover',
                    selected && 'bg-fill-selected hover:bg-fill-selected'
                )}
                // Item drops a `role` prop, so the option role goes on the rendered element.
                // eslint-disable-next-line react/forbid-elements
                render={<button type="button" role="option" disabled={isEditing} aria-disabled={isEditing} />}
                onClick={() => selectArtifact(file.key)}
                data-attr="task-artifact-nav-item"
            >
                <ItemMedia>
                    <ArtifactIcon artifact={file.latest} className="size-4 text-muted-foreground" />
                </ItemMedia>
                <ItemContent className="min-w-0">
                    <ItemTitle className="w-full truncate">{file.name}</ItemTitle>
                    <ItemDescription className="truncate">{fileMeta(file)}</ItemDescription>
                </ItemContent>
            </Item>
        )
    }
    return (
        <div
            role="listbox"
            aria-label={label}
            onKeyDown={onKeyDown}
            className="flex min-h-0 flex-1 flex-col gap-px overflow-y-auto p-1.5"
        >
            {files.filter((file) => !postHogObjectRef(file.latest)).map(renderRow)}
            {objects.length > 0 && (
                <div role="group" aria-label="In PostHog" className="flex flex-col gap-px">
                    <Text
                        size="xs"
                        weight="medium"
                        variant="muted"
                        render={<span aria-hidden />}
                        className="px-2 pt-3 pb-1"
                    >
                        In PostHog
                    </Text>
                    {objects.map(renderRow)}
                </div>
            )}
        </div>
    )
}

function ArtifactNav({ taskId }: { taskId: string }): JSX.Element {
    const { files, isEditing } = useValues(taskRunArtifactsLogic({ taskId }))
    const objectCount = files.filter((file) => !!postHogObjectRef(file.latest)).length
    return (
        <aside className="hidden w-64 shrink-0 flex-col border-r border-border @[52rem]/main-content:flex">
            <div className="flex h-10 shrink-0 items-center gap-1.5 border-b border-border px-3">
                <Text size="xs" weight="medium" variant="muted" render={<span />}>
                    Files
                </Text>
                <Text size="xs" variant="muted" render={<span />} className="tabular-nums">
                    {files.length - objectCount}
                </Text>
            </div>
            {isEditing && (
                <Text size="xs" variant="muted" className="border-b border-border px-3 py-2">
                    Save or cancel your changes to open another file.
                </Text>
            )}
            <ArtifactFileList taskId={taskId} size="xs" label="Files" />
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
                    <SelectItem key={version.id} value={version.id ?? ''} className="pe-7">
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

function CopyLinkAction({ taskId }: { taskId: string }): JSX.Element {
    const { shareUrl } = useValues(taskRunArtifactsLogic({ taskId }))
    const { reportLinkCopied } = useActions(taskRunArtifactsLogic({ taskId }))
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
            label={copied ? 'Link copied' : 'Copy link to this file'}
            disabledReason={shareUrl ? undefined : 'The file is not ready yet'}
            onClick={() => {
                if (shareUrl) {
                    void navigator.clipboard.writeText(shareUrl).then(() => {
                        setCopied(true)
                        reportLinkCopied()
                    })
                }
            }}
            dataAttr="task-artifact-copy-link"
        >
            {copied ? <IconCheck className="size-4" /> : <IconShare className="size-4" />}
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
    onExpandedChange: (expanded: boolean, source: FullPageSource) => void
}): JSX.Element {
    const {
        files,
        selectedFile,
        selectedIndex,
        selectedText,
        currentProjectId,
        selectedEditableKind,
        editDisabledReason,
        dismissalPending,
    } = useValues(taskRunArtifactsLogic({ taskId }))
    const { stepArtifact, downloadArtifact, reportObjectOpened, startEditing, dismissFile } = useActions(
        taskRunArtifactsLogic({ taskId })
    )
    const kind = artifactPreviewKind(artifact)
    const comments = commentLogicProps(taskId, artifact, kind)
    const objectRef = postHogObjectRef(artifact)
    const objectLink =
        objectRef && currentProjectId !== null
            ? objectKindLink(objectRef.objectKind, objectRef.objectId, `/project/${currentProjectId}`)
            : null
    const downloadUrl = artifactDownloadUrl(currentProjectId, taskId, artifact, { forDownload: true })
    const single = files.length < 2
    const versioned = !!selectedFile && selectedFile.versions.length > 1
    // Plain text already shows its source, so only these kinds get a view switch.
    const hasRenderedForm = kind === 'markdown' || kind === 'html' || kind === 'csv'
    return (
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-background px-3">
            <ArtifactIcon artifact={artifact} className="size-4 shrink-0 text-muted-foreground" />
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
                        {`${artifactDetail(artifact)} · ${dayjs(artifact.uploaded_at).fromNow()}`}
                    </Text>
                </TooltipTrigger>
                <TooltipContent>
                    {`${artifact.name} · ${artifactDetail(artifact)} · ${dayjs(artifact.uploaded_at).format('MMM D, YYYY HH:mm')}`}
                </TooltipContent>
            </Tooltip>
            {versioned && selectedFile && <VersionSelect taskId={taskId} file={selectedFile} />}
            {kind === 'html' && (
                <Tooltip>
                    <TooltipTrigger className="shrink-0">
                        <Badge>
                            <IconLock />
                            Sandboxed
                        </Badge>
                    </TooltipTrigger>
                    <TooltipContent>
                        This artifact runs scripts in an isolated frame. It cannot access your PostHog cookies or
                        session. It can send its contents and anything you enter to external sites.
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
                {selectedEditableKind && (
                    <IconAction
                        label="Edit"
                        disabledReason={editDisabledReason ?? undefined}
                        onClick={() => startEditing()}
                        dataAttr="task-artifact-edit"
                    >
                        <IconPencil className="size-4" />
                    </IconAction>
                )}
                {comments && <ArtifactCommentActions logicProps={comments} />}
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
                <CopyLinkAction taskId={taskId} />
                {/* PostHog stores only the files of a living document. Canvas and message text has no file to download. */}
                {kind !== 'reference' && (!artifact.living || artifact.living.stored) && (
                    <IconAction
                        label={versioned ? 'Download this version' : 'Download'}
                        href={downloadUrl ?? undefined}
                        disabledReason={downloadUrl ? undefined : 'The file is not ready yet'}
                        onClick={() => downloadArtifact(artifact)}
                        dataAttr="task-artifact-download"
                    >
                        <IconDownload className="size-4" />
                    </IconAction>
                )}
                {objectLink?.url && objectRef && (
                    <IconAction
                        label={`Open ${lowerFirst(objectLink.kind.kindLabel)} page`}
                        to={objectLink.url}
                        onClick={() => reportObjectOpened(objectRef.objectKind)}
                        dataAttr="task-artifact-open-object-page"
                    >
                        <IconExternal className="size-4" />
                    </IconAction>
                )}
                {/* No endpoint dismisses a living document, so it has no dismissal. */}
                {selectedFile && !artifact.living && (
                    <IconAction
                        label="Dismiss artifact"
                        loading={dismissalPending}
                        onClick={() => dismissFile(selectedFile.key)}
                        dataAttr="task-artifact-dismiss"
                    >
                        <IconHide className="size-4" />
                    </IconAction>
                )}
                {/* Full page always keeps its exit, because the stepper can land on an object with no embed. */}
                {(expanded || hasFullPageView(artifact)) && (
                    <IconAction
                        label={expanded ? 'Exit full page' : 'Open full page'}
                        shortcut={hasFullPageShortcut(artifact) ? FULL_PAGE_KEY.toUpperCase() : undefined}
                        onClick={() => onExpandedChange(!expanded, 'button')}
                        dataAttr={expanded ? 'task-artifact-collapse' : 'task-artifact-expand'}
                    >
                        {expanded ? <IconCollapse45 className="size-4" /> : <IconExpand45 className="size-4" />}
                    </IconAction>
                )}
            </div>
        </div>
    )
}

function copyWithToast(text: string, title: string, onCopied?: () => void): void {
    void navigator.clipboard.writeText(text).then(() => {
        toast.success({ title })
        onCopied?.()
    })
}

function PhoneArtifactHeader({
    taskId,
    artifact,
    mode,
    onModeChange,
}: {
    taskId: string
    artifact: RunArtifact
    mode: PreviewMode
    onModeChange: (mode: PreviewMode) => void
}): JSX.Element {
    const { selectedFile, selectedText, currentProjectId, selectedEditableKind, editDisabledReason, shareUrl } =
        useValues(taskRunArtifactsLogic({ taskId }))
    const { closeArtifact, downloadArtifact, reportObjectOpened, startEditing, dismissFile, reportLinkCopied } =
        useActions(taskRunArtifactsLogic({ taskId }))
    const [menuOpen, setMenuOpen] = useState(false)
    const kind = artifactPreviewKind(artifact)
    const comments = commentLogicProps(taskId, artifact, kind)
    const objectRef = postHogObjectRef(artifact)
    const objectLink =
        objectRef && currentProjectId !== null
            ? objectKindLink(objectRef.objectKind, objectRef.objectId, `/project/${currentProjectId}`)
            : null
    const downloadUrl = artifactDownloadUrl(currentProjectId, taskId, artifact, { forDownload: true })
    const versioned = !!selectedFile && selectedFile.versions.length > 1
    const hasRenderedForm = kind === 'markdown' || kind === 'html' || kind === 'csv'
    const canDownload = kind !== 'reference' && (!artifact.living || artifact.living.stored)
    return (
        <>
            <div className="flex h-12 shrink-0 items-center gap-1 border-b border-border bg-background px-1">
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                size="icon-lg"
                                aria-label="Back to artifacts"
                                onClick={closeArtifact}
                                data-attr="task-artifact-back"
                            />
                        }
                    >
                        <IconChevronLeft />
                    </TooltipTrigger>
                    <TooltipContent>Back to artifacts</TooltipContent>
                </Tooltip>
                <ArtifactIcon artifact={artifact} className="size-4 shrink-0 text-muted-foreground" />
                <span className="flex min-w-0 flex-1 flex-col pl-1">
                    <Text size="sm" weight="medium" render={<span />} className="truncate">
                        {artifact.name}
                    </Text>
                    <Text size="xs" variant="muted" render={<span />} className="truncate tabular-nums">
                        {`${artifactDetail(artifact)} · ${dayjs(artifact.uploaded_at).fromNow()}`}
                    </Text>
                </span>
                {comments && <ArtifactCommentsButton logicProps={comments} />}
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                size="icon-lg"
                                aria-label="More actions"
                                onClick={() => setMenuOpen(true)}
                                data-attr="task-artifact-more"
                            />
                        }
                    >
                        <IconEllipsis />
                    </TooltipTrigger>
                    <TooltipContent>More actions</TooltipContent>
                </Tooltip>
            </div>
            {(hasRenderedForm || versioned) && (
                <div className="flex shrink-0 items-center gap-2 border-b border-border bg-background px-3 py-1.5">
                    {hasRenderedForm && (
                        <ToggleGroup
                            variant="outline"
                            value={[mode]}
                            onValueChange={(value: string[]) => value[0] && onModeChange(value[0] as PreviewMode)}
                            aria-label="View"
                        >
                            <ToggleGroupItem value="rendered" data-attr="task-artifact-view-rendered">
                                Preview
                            </ToggleGroupItem>
                            <ToggleGroupItem value="source" data-attr="task-artifact-view-source">
                                Source
                            </ToggleGroupItem>
                        </ToggleGroup>
                    )}
                    {versioned && selectedFile && (
                        <div className="ml-auto">
                            <VersionSelect taskId={taskId} file={selectedFile} />
                        </div>
                    )}
                </div>
            )}
            <TodaySheetMenu
                open={menuOpen}
                onOpenChange={setMenuOpen}
                title={artifact.name}
                description={artifactDetail(artifact)}
            >
                {selectedEditableKind && (
                    <SHEET_PARTS.Item
                        onClick={() => startEditing()}
                        disabled={!!editDisabledReason}
                        dataAttr="task-artifact-sheet-edit"
                    >
                        <IconPencil />
                        Edit
                    </SHEET_PARTS.Item>
                )}
                {isTextPreview(kind) && (
                    <SHEET_PARTS.Item
                        onClick={() => selectedText?.text && copyWithToast(selectedText.text, 'Source copied')}
                        disabled={typeof selectedText?.text !== 'string'}
                        dataAttr="task-artifact-sheet-copy"
                    >
                        <IconCopy />
                        Copy source
                    </SHEET_PARTS.Item>
                )}
                <SHEET_PARTS.Item
                    onClick={() => shareUrl && copyWithToast(shareUrl, 'Link copied', reportLinkCopied)}
                    disabled={!shareUrl}
                    dataAttr="task-artifact-sheet-copy-link"
                >
                    <IconShare />
                    Copy link
                </SHEET_PARTS.Item>
                {canDownload && (
                    <SHEET_PARTS.Item
                        onClick={() => {
                            if (downloadUrl) {
                                downloadArtifact(artifact)
                                window.location.assign(downloadUrl)
                            }
                        }}
                        disabled={!downloadUrl}
                        dataAttr="task-artifact-sheet-download"
                    >
                        <IconDownload />
                        {versioned ? 'Download this version' : 'Download'}
                    </SHEET_PARTS.Item>
                )}
                {objectLink?.url && objectRef && (
                    <SHEET_PARTS.Item
                        to={objectLink.url}
                        onClick={() => reportObjectOpened(objectRef.objectKind)}
                        dataAttr="task-artifact-sheet-open-object-page"
                    >
                        <IconExternal />
                        {`Open ${lowerFirst(objectLink.kind.kindLabel)} page`}
                    </SHEET_PARTS.Item>
                )}
                {selectedFile && !artifact.living && (
                    <>
                        <SHEET_PARTS.Separator />
                        <SHEET_PARTS.Item
                            onClick={() => dismissFile(selectedFile.key)}
                            dataAttr="task-artifact-sheet-dismiss"
                        >
                            <IconHide />
                            Dismiss artifact
                        </SHEET_PARTS.Item>
                    </>
                )}
            </TodaySheetMenu>
        </>
    )
}

function PreviewSurface({ taskId, mode }: { taskId: string; mode: PreviewMode }): JSX.Element {
    const { selectedKind, isEditing } = useValues(taskRunArtifactsLogic({ taskId }))
    if (isEditing) {
        return <ArtifactEditor taskId={taskId} />
    }
    const fills =
        mode === 'rendered' &&
        (selectedKind === 'html' ||
            selectedKind === 'image' ||
            selectedKind === 'video' ||
            selectedKind === 'reference')
    return (
        <div className={cn('min-h-0 flex-1 bg-surface-tertiary', fills ? 'flex flex-col' : 'overflow-y-auto')}>
            <ArtifactPreview taskId={taskId} mode={mode} />
        </div>
    )
}

function PreviewBody({ taskId, mode }: { taskId: string; mode: PreviewMode }): JSX.Element {
    return (
        <div className="relative flex min-h-0 flex-1">
            <div className="flex min-w-0 flex-1 flex-col">
                <OlderVersionNotice taskId={taskId} />
                <PreviewSurface taskId={taskId} mode={mode} />
            </div>
        </div>
    )
}

function ArtifactsWorkspace({ taskId }: { taskId: string }): JSX.Element {
    const { files, selectedArtifact, isEditing, todayPhone, showArtifactList, commentsOpen } = useValues(
        taskRunArtifactsLogic({ taskId })
    )
    const { setActiveTab, reportFullPageOpened } = useActions(taskRunArtifactsLogic({ taskId }))
    const [mode, setMode] = useState<PreviewMode>('rendered')
    const [expanded, setExpanded] = useState(false)
    // A new file opens in its rendered form, whatever the last file showed.
    useEffect(() => setMode('rendered'), [selectedArtifact?.id])
    const changeExpanded = (next: boolean, source: FullPageSource): void => {
        setExpanded(next)
        if (next) {
            reportFullPageOpened(source)
        }
    }
    // The hook skips key presses in inputs, text areas and editable content, so typing never toggles the view.
    useKeyboardHotkeys(
        {
            [FULL_PAGE_KEY]: {
                action: () => changeExpanded(!expanded, 'keyboard'),
                disabled:
                    !selectedArtifact ||
                    !hasFullPageShortcut(selectedArtifact) ||
                    (!expanded && !hasFullPageView(selectedArtifact)),
            },
        },
        [expanded, selectedArtifact]
    )

    // A dismissal while editing can empty the list, and the editor must stay to keep the draft.
    if (!isEditing && (files.length === 0 || !selectedArtifact)) {
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
    if (showArtifactList && !isEditing) {
        return <ArtifactFileList taskId={taskId} size="sm" label="Artifacts" />
    }
    const phoneComments =
        todayPhone && commentsOpen && selectedArtifact && !isEditing
            ? commentLogicProps(taskId, selectedArtifact, artifactPreviewKind(selectedArtifact))
            : null
    if (phoneComments && selectedArtifact) {
        return <ArtifactCommentsPage logicProps={phoneComments} artifactName={selectedArtifact.name} />
    }
    const toolbar =
        todayPhone && selectedArtifact && !isEditing ? (
            <PhoneArtifactHeader taskId={taskId} artifact={selectedArtifact} mode={mode} onModeChange={setMode} />
        ) : selectedArtifact && !isEditing ? (
            <ArtifactToolbar
                taskId={taskId}
                artifact={selectedArtifact}
                mode={mode}
                onModeChange={setMode}
                expanded={expanded}
                onExpandedChange={changeExpanded}
            />
        ) : (
            <ArtifactEditToolbar
                taskId={taskId}
                expandAction={
                    <IconAction
                        label={expanded ? 'Exit full page' : 'Open full page'}
                        onClick={() => changeExpanded(!expanded, 'button')}
                        dataAttr={expanded ? 'task-artifact-collapse' : 'task-artifact-expand'}
                    >
                        {expanded ? <IconCollapse45 className="size-4" /> : <IconExpand45 className="size-4" />}
                    </IconAction>
                }
            />
        )
    return (
        <div className="flex min-h-0 flex-1">
            <ArtifactNav taskId={taskId} />
            <section className="flex min-w-0 flex-1 flex-col">
                {toolbar}
                {!expanded && <PreviewBody taskId={taskId} mode={mode} />}
            </section>
            <Dialog open={expanded} onOpenChange={setExpanded}>
                {/* Full page covers the whole window, so the dialog drops its inset, corners and shadow. */}
                <DialogContent
                    showCloseButton={false}
                    className="inset-0 flex h-dvh max-h-none w-screen max-w-none translate-none flex-col gap-0 rounded-none p-0 shadow-none"
                >
                    <DialogTitle className="sr-only">{selectedArtifact?.name ?? 'Artifact'}</DialogTitle>
                    {/* The toolbar hides parts by container width, so the dialog gets its own container. */}
                    <div className="@container/main-content flex min-h-0 flex-1 flex-col">
                        {toolbar}
                        <PreviewBody taskId={taskId} mode={mode} />
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
