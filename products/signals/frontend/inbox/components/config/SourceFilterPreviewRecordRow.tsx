import clsx from 'clsx'

import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { SourceFilterPreviewRecordApi } from 'products/signals/frontend/generated/api.schemas'

export interface SourceFilterPreviewRecordRowProps {
    record: SourceFilterPreviewRecordApi
    /** What one record of the source is called, such as "issue". */
    noun: string
}

export function SourceFilterPreviewRecordRow({ record, noun }: SourceFilterPreviewRecordRowProps): JSX.Element {
    const linkLabel = record.identifier ?? 'Open'
    return (
        <li className="flex min-w-0 items-center gap-2 py-1.5">
            {record.url ? (
                <Link
                    to={record.url}
                    target="_blank"
                    className="shrink-0 font-mono text-xs"
                    data-attr="signal-source-filter-preview-record"
                >
                    {linkLabel}
                </Link>
            ) : record.identifier ? (
                <span className="shrink-0 font-mono text-xs text-secondary">{record.identifier}</span>
            ) : null}
            <span
                className={clsx('min-w-0 flex-1 truncate text-sm', !record.title && 'text-muted')}
                title={record.title ?? undefined}
            >
                {record.title ?? 'Untitled'}
            </span>
            {record.malformed && (
                <Tooltip
                    title={`A field this filter uses holds a value that can't be read, so this ${noun} never passes.`}
                >
                    <LemonTag type="warning" size="small" className="shrink-0">
                        Unreadable
                    </LemonTag>
                </Tooltip>
            )}
            {record.created_at && (
                <span className="hidden shrink-0 text-xs text-muted @md:block">
                    <TZLabel time={record.created_at} />
                </span>
            )}
        </li>
    )
}
