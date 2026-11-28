import clsx from 'clsx'
import { Fragment } from 'react'

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
    const failedConditions = record.failed_conditions ?? []
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
            <div className="flex min-w-0 flex-1 flex-col">
                <span
                    className={clsx('truncate text-sm', !record.title && 'text-muted')}
                    title={record.title ?? undefined}
                >
                    {record.title ?? 'Untitled'}
                </span>
                {failedConditions.length > 0 && (
                    // The line clips after two lines, so a tap opens the full list on screens without hover.
                    // Conditions hold the person's own filter values, so autocapture must not record them.
                    <Tooltip
                        title={
                            <span className="ph-no-capture flex flex-col gap-1 font-mono text-xs" translate="no">
                                {failedConditions.map((condition, index) => (
                                    <span key={index}>{condition}</span>
                                ))}
                            </span>
                        }
                        placement="bottom-start"
                        openOnClick
                        interactive
                        className="max-h-[50vh] overflow-y-auto"
                    >
                        <button
                            type="button"
                            className="ph-no-capture line-clamp-2 max-w-full cursor-pointer self-start text-left text-xs text-muted"
                            data-attr="signal-source-filter-preview-failed-conditions"
                        >
                            <span>Fails </span>
                            {failedConditions.map((condition, index) => (
                                <Fragment key={index}>
                                    {index > 0 && <span className="font-mono"> · </span>}
                                    <span className="font-mono" translate="no">
                                        {condition}
                                    </span>
                                </Fragment>
                            ))}
                        </button>
                    </Tooltip>
                )}
            </div>
            {record.malformed && (
                <Tooltip
                    title="This item is excluded because it contains values that can't be parsed by the filter."
                    openOnClick
                >
                    <button
                        type="button"
                        className="shrink-0 cursor-pointer"
                        aria-label={`Why this ${noun} is unreadable`}
                        data-attr="signal-source-filter-preview-unreadable"
                    >
                        <LemonTag type="warning" size="small">
                            Unreadable
                        </LemonTag>
                    </button>
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
