import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconArrowLeft, IconCheck, IconCopy, IconExternal, IconPencil } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, Link, Spinner } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'

import { MonitorPicker } from './MonitorPicker'
import { statusPageLogic, StatusPageLogicProps } from './statusPageLogic'
import { StatusPagePreview } from './StatusPagePreview'

export const scene: SceneExport<StatusPageLogicProps> = {
    component: StatusPageSceneWrapper,
    logic: statusPageLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

function StatusPageSceneWrapper(): JSX.Element {
    return <StatusPageScene />
}

function StatusPageScene(): JSX.Element {
    const { statusPage, statusPageLoading, selectedMonitors, displayTitle } = useValues(statusPageLogic)

    if (statusPageLoading && !statusPage) {
        return (
            <div className="flex items-center justify-center p-12">
                <Spinner />
            </div>
        )
    }

    if (!statusPage) {
        return <div className="p-8 text-center text-secondary">Status page not found.</div>
    }

    return (
        <div className="flex flex-col h-full min-h-0">
            <StatusPageHeader />
            <div className="grid gap-4 grow min-h-0" style={{ gridTemplateColumns: '320px 1fr' }}>
                <aside className="border rounded p-3 bg-surface-primary overflow-hidden flex flex-col">
                    <MonitorPicker />
                </aside>
                <section className="border rounded p-6 bg-surface-secondary overflow-y-auto">
                    <StatusPagePreview
                        title={displayTitle}
                        monitors={selectedMonitors}
                        publishedAt={statusPage.published_at}
                    />
                </section>
            </div>
        </div>
    )
}

function StatusPageHeader(): JSX.Element {
    const { statusPage, displayTitle, displaySlug, publicUrl, urlPopoverOpen, statusPageLoading } =
        useValues(statusPageLogic)
    const {
        setDraftTitle,
        commitTitle,
        setDraftSlug,
        commitSlug,
        clearDraftSlug,
        publish,
        unpublish,
        setUrlPopoverOpen,
    } = useActions(statusPageLogic)

    if (!statusPage) {
        return <div />
    }

    return (
        <header className="flex items-center justify-between gap-3 mb-4 flex-wrap">
            <div className="flex items-center gap-2 min-w-0">
                <LemonButton
                    icon={<IconArrowLeft />}
                    to="/uptime?activeTab=status_pages"
                    size="small"
                    type="tertiary"
                    tooltip="Back to status pages"
                />
                <InlineTitle value={displayTitle} onChange={setDraftTitle} onCommit={commitTitle} />
                {statusPageLoading && <Spinner className="text-secondary" />}
            </div>
            <div className="flex items-center gap-2 shrink-0">
                <SlugEditor
                    slug={displaySlug}
                    publicUrl={publicUrl}
                    onChange={setDraftSlug}
                    onCommit={commitSlug}
                    onCancel={clearDraftSlug}
                />
                <PublishControl
                    isPublished={statusPage.is_published}
                    publicUrl={publicUrl}
                    urlPopoverOpen={urlPopoverOpen}
                    onOpenChange={setUrlPopoverOpen}
                    onPublish={publish}
                    onUnpublish={unpublish}
                />
            </div>
        </header>
    )
}

function InlineTitle({
    value,
    onChange,
    onCommit,
}: {
    value: string
    onChange: (v: string) => void
    onCommit: () => void
}): JSX.Element {
    const [editing, setEditing] = useState(false)
    const inputRef = useRef<HTMLInputElement | null>(null)

    useEffect(() => {
        if (editing) {
            inputRef.current?.focus()
            inputRef.current?.select()
        }
    }, [editing])

    if (!editing) {
        return (
            <button
                type="button"
                onClick={() => setEditing(true)}
                className="group flex items-center gap-2 px-2 py-1 rounded -mx-2 hover:bg-surface-secondary transition-colors"
                title="Click to rename"
            >
                <span className="text-lg font-semibold truncate max-w-[28ch]">{value}</span>
                <IconPencil className="text-secondary opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
        )
    }

    return (
        <LemonInput
            inputRef={inputRef}
            size="small"
            value={value}
            onChange={onChange}
            onBlur={() => {
                onCommit()
                setEditing(false)
            }}
            onPressEnter={() => {
                onCommit()
                setEditing(false)
            }}
            className="max-w-[36ch]"
        />
    )
}

function SlugEditor({
    slug,
    publicUrl,
    onChange,
    onCommit,
    onCancel,
}: {
    slug: string
    publicUrl: string | null
    onChange: (v: string) => void
    onCommit: () => void
    onCancel: () => void
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const inputRef = useRef<HTMLInputElement | null>(null)

    useEffect(() => {
        if (open) {
            inputRef.current?.focus()
        }
    }, [open])

    return (
        <Popover
            visible={open}
            onClickOutside={() => {
                onCommit()
                setOpen(false)
            }}
            overlay={
                <div className="flex flex-col gap-2 p-3 w-80">
                    <label className="text-xs text-secondary font-medium uppercase tracking-wide">URL slug</label>
                    <div className="flex items-center gap-2">
                        <span className="text-xs text-secondary font-mono">/status/</span>
                        <LemonInput
                            inputRef={inputRef}
                            size="small"
                            value={slug}
                            onChange={onChange}
                            onPressEnter={() => {
                                onCommit()
                                setOpen(false)
                            }}
                            placeholder="my-status-page"
                            fullWidth
                        />
                    </div>
                    {publicUrl && (
                        <div className="text-[11px] text-secondary truncate" title={publicUrl}>
                            {publicUrl}
                        </div>
                    )}
                    <div className="flex justify-end gap-2 mt-1">
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => {
                                onCancel()
                                setOpen(false)
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="primary"
                            onClick={() => {
                                onCommit()
                                setOpen(false)
                            }}
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonButton size="small" type="secondary" onClick={() => setOpen((v) => !v)}>
                <span className="font-mono text-xs">/status/{slug}</span>
            </LemonButton>
        </Popover>
    )
}

function PublishControl({
    isPublished,
    publicUrl,
    urlPopoverOpen,
    onOpenChange,
    onPublish,
    onUnpublish,
}: {
    isPublished: boolean
    publicUrl: string | null
    urlPopoverOpen: boolean
    onOpenChange: (open: boolean) => void
    onPublish: () => void
    onUnpublish: () => void
}): JSX.Element {
    if (!isPublished) {
        return (
            <LemonButton type="primary" onClick={onPublish}>
                Publish
            </LemonButton>
        )
    }

    return (
        <Popover
            visible={urlPopoverOpen}
            onClickOutside={() => onOpenChange(false)}
            overlay={
                <LivePopoverContent
                    publicUrl={publicUrl}
                    onUnpublish={() => {
                        onOpenChange(false)
                        onUnpublish()
                    }}
                    onClose={() => onOpenChange(false)}
                />
            }
        >
            <LemonButton type="secondary" onClick={() => onOpenChange(!urlPopoverOpen)} size="small">
                <span className="flex items-center gap-2">
                    <span className={cn('w-2 h-2 rounded-full bg-success')} aria-hidden />
                    <span className="font-medium">Live</span>
                </span>
            </LemonButton>
        </Popover>
    )
}

function LivePopoverContent({
    publicUrl,
    onUnpublish,
    onClose,
}: {
    publicUrl: string | null
    onUnpublish: () => void
    onClose: () => void
}): JSX.Element {
    const [copied, setCopied] = useState(false)

    const onCopy = async (): Promise<void> => {
        if (!publicUrl) {
            return
        }
        const ok = await copyToClipboard(publicUrl, 'status page URL')
        if (ok) {
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
        }
    }

    return (
        <div className="flex flex-col gap-3 p-3 w-80">
            <div className="flex flex-col gap-1">
                <span className="text-xs uppercase tracking-wide text-secondary font-medium">Public URL</span>
                <div className="flex items-center gap-2">
                    <code className="flex-1 text-xs font-mono truncate bg-surface-secondary px-2 py-1 rounded">
                        {publicUrl}
                    </code>
                    <LemonButton
                        size="small"
                        icon={copied ? <IconCheck /> : <IconCopy />}
                        onClick={onCopy}
                        tooltip="Copy URL"
                    />
                    {publicUrl && (
                        <Link to={publicUrl} target="_blank" onClick={onClose}>
                            <LemonButton size="small" icon={<IconExternal />} tooltip="Open in new tab" />
                        </Link>
                    )}
                </div>
            </div>
            <LemonMenu
                items={[
                    {
                        label: 'Revert to draft',
                        onClick: onUnpublish,
                        status: 'danger',
                    },
                ]}
            >
                <LemonButton size="small" type="secondary" fullWidth>
                    More actions
                </LemonButton>
            </LemonMenu>
        </div>
    )
}
