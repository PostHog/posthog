import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { ErrorTrackingAlertPreviewApi, ErrorTrackingAlertPreviewMessageApi } from '../../../../generated/api.schemas'

const EVENT_LABELS: Record<string, string> = {
    $error_tracking_issue_created: 'Issue created',
    $error_tracking_issue_reopened: 'Issue reopened',
    $error_tracking_issue_spiking: 'Issue spiking',
    $error_tracking_issue_assigned: 'Issue assigned',
    $error_tracking_issue_resolved: 'Issue resolved',
    $error_tracking_issue_suppressed: 'Issue suppressed',
}

type SlackBlock = Record<string, any>

function blockText(block: SlackBlock): string {
    return typeof block?.text === 'string' ? block.text : (block?.text?.text ?? '')
}

function RootBlocks({ blocks }: { blocks: SlackBlock[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            {blocks.map((block, index) => {
                switch (block.type) {
                    case 'header':
                        return (
                            <div key={index} className="text-base font-bold leading-tight">
                                {blockText(block)}
                            </div>
                        )
                    case 'section':
                        return (
                            <div key={index} className="text-sm whitespace-pre-wrap">
                                {blockText(block)}
                            </div>
                        )
                    case 'context':
                        return (
                            <div key={index} className="text-xs text-secondary">
                                {(block.elements ?? []).map((element: SlackBlock) => element.text).join(' · ')}
                            </div>
                        )
                    case 'actions':
                        return (
                            <div key={index} className="flex gap-2 pt-1">
                                {(block.elements ?? []).map((element: SlackBlock, i: number) => (
                                    <span
                                        key={i}
                                        className="inline-flex items-center h-7 px-2.5 border rounded text-xs font-semibold"
                                    >
                                        {blockText(element)}
                                    </span>
                                ))}
                            </div>
                        )
                    default:
                        return null
                }
            })}
        </div>
    )
}

function Message({ message, edited }: { message: ErrorTrackingAlertPreviewMessageApi; edited: boolean }): JSX.Element {
    const isRoot = message.kind !== 'reply'
    return (
        <div className={isRoot ? 'flex gap-2.5' : 'flex gap-2.5 ml-4 pl-3 border-l-2'}>
            <div
                className={
                    isRoot
                        ? 'w-8 h-8 rounded bg-fill-highlight-100 shrink-0'
                        : 'w-5 h-5 rounded bg-fill-highlight-100 shrink-0'
                }
            />
            <div className="flex flex-col gap-1 min-w-0 flex-1">
                <div className="flex items-center gap-2 text-xs text-secondary">
                    <span className="font-semibold text-primary">PostHog</span>
                    <LemonTag size="small" type={isRoot ? 'highlight' : 'default'}>
                        {EVENT_LABELS[message.event] ?? message.event}
                    </LemonTag>
                    {edited && <span>edited</span>}
                </div>
                {isRoot && message.blocks ? (
                    <RootBlocks blocks={message.blocks} />
                ) : (
                    <div className="text-sm">{message.text}</div>
                )}
            </div>
        </div>
    )
}

export function AlertPreview({
    preview,
    loading,
    channelLabel,
}: {
    preview: ErrorTrackingAlertPreviewApi | null
    loading: boolean
    channelLabel: string | null
}): JSX.Element {
    const messages = preview?.messages ?? []
    // The root edit replaces the root in Slack; show it as the final state instead of a fourth message.
    const rootEdit = messages.find((message) => message.kind === 'root_edit')
    const timeline = messages.filter((message) => message.kind !== 'root_edit')

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase text-secondary">
                    Preview{channelLabel ? ` · what ${channelLabel} will see` : ''}
                </span>
                {preview?.issue_id ? (
                    <span className="text-xs text-secondary">Rendered from your most recent issue</span>
                ) : preview ? (
                    <span className="text-xs text-secondary">Sample issue, none in this project yet</span>
                ) : null}
            </div>
            <div className="flex flex-col gap-3 p-4 border rounded bg-surface-primary">
                {loading && !preview ? (
                    <>
                        <LemonSkeleton className="h-6 w-2/3" />
                        <LemonSkeleton className="h-4 w-1/2" />
                        <LemonSkeleton className="h-4 w-1/3" />
                    </>
                ) : (
                    timeline.map((message, index) => (
                        <Message
                            key={index}
                            message={message.kind === 'root' && rootEdit ? { ...rootEdit, kind: 'root' } : message}
                            edited={message.kind === 'root' && !!rootEdit}
                        />
                    ))
                )}
            </div>
            <span className="text-xs text-secondary">
                The thread opens on the first matching trigger. Every later change to the issue is a reply, and the
                status line on the root is kept up to date.
            </span>
        </div>
    )
}
