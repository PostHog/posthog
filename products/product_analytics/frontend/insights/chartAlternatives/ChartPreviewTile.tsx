import clsx from 'clsx'

import { IconInfo } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { ChartDisplayIcon } from './ChartDisplayIcon'
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
    const { option, warning } = preview
    const reason = disabledReason ?? option.disabledReason
    const disabled = !!reason

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
            <span className="flex h-32 flex-col items-center justify-center gap-2 px-4 text-center text-secondary">
                <span className="text-4xl opacity-40">
                    <ChartDisplayIcon icon={option.icon} />
                </span>
                {reason ? <span className="text-xs">{reason}</span> : null}
            </span>
            {warning && !reason ? (
                <span className="flex items-center border-t px-2 py-1 text-xs text-warning">{warning.title}</span>
            ) : null}
        </button>
    )

    return reason ? <Tooltip title={reason}>{tile}</Tooltip> : tile
}
