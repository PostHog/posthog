import clsx from 'clsx'

import { IconInfo } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { ChartDisplayType } from '~/types'

import { ChartDisplayIcon } from './ChartDisplayIcon'
import { ChartPreviewCanvas } from './ChartPreviewCanvas'
import type { ChartPreview } from './chartPreviewsLogic'

export function ChartPreviewTile({
    disabledReason,
    onSelect,
    preview,
}: {
    disabledReason?: string
    onSelect: () => void
    preview: ChartPreview
}): JSX.Element {
    const { loading, option, query, response, sample, uniqueKey, warning } = preview
    const reason = disabledReason ?? option.disabledReason
    const disabled = !!reason

    let body: JSX.Element
    if (response) {
        body = <ChartPreviewCanvas uniqueKey={uniqueKey} query={query} response={response} />
    } else if (loading) {
        body = (
            <div className="flex flex-1 items-center justify-center">
                <Spinner />
            </div>
        )
    } else {
        body = (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 px-4 text-center text-secondary">
                <span className="text-4xl opacity-40">
                    <ChartDisplayIcon icon={option.icon} />
                </span>
                {reason ? <span className="text-xs">{reason}</span> : null}
            </div>
        )
    }

    const tile = (
        <button
            type="button"
            className={clsx(
                'flex w-full flex-col overflow-hidden rounded border bg-surface-primary text-left transition-colors',
                disabled ? 'cursor-default' : 'cursor-pointer hover:border-accent hover:bg-surface-secondary',
                reason && 'opacity-60'
            )}
            data-attr={`chart-preview-${option.display}`}
            disabled={disabled}
            onClick={onSelect}
        >
            <span className="flex items-center gap-1 border-b px-2 py-1 text-xs">
                <ChartDisplayIcon icon={option.icon} />
                <span className="truncate font-medium">{option.label}</span>
                <Tooltip title={option.description}>
                    <IconInfo className="ml-auto shrink-0 text-base text-secondary" />
                </Tooltip>
            </span>
            <span className="pointer-events-none relative flex h-32 flex-col overflow-hidden" aria-hidden>
                <span
                    className={clsx(
                        'flex h-full flex-col [&_.text-7xl]:text-lg [&_.text-7xl]:leading-tight',
                        option.display === ChartDisplayType.CalendarHeatmap &&
                            '[zoom:0.3] [&_.CalendarHeatMapContainer+div]:hidden',
                        option.display === ChartDisplayType.ActionsTable &&
                            '[zoom:0.6] [&_.ScrollableShadows::before]:shadow-none! [&_.ScrollableShadows::after]:shadow-none! [&_.LemonTable__cell--sticky::before]:shadow-none! [&_.LemonTable__header--sticky::before]:shadow-none!'
                    )}
                >
                    {body}
                </span>
            </span>
            {warning && !reason ? (
                <span className="flex items-center border-t px-2 py-1 text-xs text-warning">{warning.title}</span>
            ) : null}
            {sample && !reason ? (
                <Tooltip title="Shows how this chart type looks. Select it to run the query on your data.">
                    <span className="flex items-center gap-1 border-t px-2 py-1 text-xs text-secondary">
                        Sample data
                        <IconInfo className="ml-auto shrink-0 text-base" />
                    </span>
                </Tooltip>
            ) : null}
        </button>
    )

    return reason ? <Tooltip title={reason}>{tile}</Tooltip> : tile
}
