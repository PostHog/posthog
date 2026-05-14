import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconCopy, IconExternal, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { statusPagesListLogic, StatusPageListItem } from './statusPagesListLogic'

export function StatusPagesList(): JSX.Element {
    const { statusPages, statusPagesLoading } = useValues(statusPagesListLogic)
    const { deleteStatusPage } = useActions(statusPagesListLogic)

    if (!statusPagesLoading && statusPages.length === 0) {
        return <EmptyState />
    }

    return (
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>
            {statusPages.map((page) => (
                <StatusPageCard key={page.id} page={page} onDelete={() => deleteStatusPage(page.id)} />
            ))}
        </div>
    )
}

function StatusPageCard({ page, onDelete }: { page: StatusPageListItem; onDelete: () => void }): JSX.Element {
    const monitorCount = page.monitor_ids.length
    const publicUrl =
        typeof window !== 'undefined' ? `${window.location.origin}/status/${page.slug}` : `/status/${page.slug}`
    return (
        <LemonCard className="flex flex-col gap-3 p-4">
            <div className="flex items-start justify-between gap-2 min-w-0">
                <Link to={`/uptime/status-pages/${page.id}`} className="font-semibold truncate min-w-0">
                    {page.title || 'Untitled status page'}
                </Link>
                {page.is_published ? (
                    <LemonTag type="success" size="small">
                        Live
                    </LemonTag>
                ) : (
                    <LemonTag type="muted" size="small">
                        Draft
                    </LemonTag>
                )}
            </div>
            <div className="flex items-center justify-between text-xs text-secondary">
                <span>
                    {monitorCount} monitor{monitorCount === 1 ? '' : 's'}
                </span>
                <span>Updated {dayjs(page.updated_at).fromNow()}</span>
            </div>
            <div className="flex items-center gap-1">
                <LemonButton type="secondary" size="small" to={`/uptime/status-pages/${page.id}`}>
                    Edit
                </LemonButton>
                {page.is_published && (
                    <>
                        <CopyButton text={publicUrl} />
                        <Link to={publicUrl} target="_blank">
                            <LemonButton size="small" icon={<IconExternal />} tooltip="Open public page" />
                        </Link>
                    </>
                )}
                <LemonButton
                    size="small"
                    type="tertiary"
                    icon={<IconTrash />}
                    onClick={onDelete}
                    status="danger"
                    tooltip="Delete"
                    className="ml-auto"
                />
            </div>
        </LemonCard>
    )
}

function CopyButton({ text }: { text: string }): JSX.Element {
    const [copied, setCopied] = useState(false)
    return (
        <Tooltip title={copied ? 'Copied' : 'Copy URL'}>
            <LemonButton
                size="small"
                icon={copied ? <IconCheck /> : <IconCopy />}
                onClick={async () => {
                    const ok = await copyToClipboard(text, 'status page URL')
                    if (ok) {
                        setCopied(true)
                        setTimeout(() => setCopied(false), 1500)
                    }
                }}
            />
        </Tooltip>
    )
}

function EmptyState(): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col items-center gap-3 p-8 text-center">
            <div className="text-xl font-semibold">No status pages yet</div>
            <div className="text-secondary">Group your monitors into a public page customers can subscribe to.</div>
        </LemonCard>
    )
}
