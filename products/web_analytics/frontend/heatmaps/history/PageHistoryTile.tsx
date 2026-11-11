import { useState } from 'react'

import { IconCamera, IconCheck, IconClock, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

import type { HeatmapScreenshotHistoryItemApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { isUsableCapture } from './pageHistoryLogic'
import { formatCaptureDay, formatCaptureTime } from './pageHistoryUtils'

function describeCaptureFailure(capture: HeatmapScreenshotHistoryItemApi): string {
    const cause = capture.latest_request?.failure_cause ?? capture.failure_cause
    const pageStatus = capture.latest_request?.page_status ?? capture.page_status
    const reason =
        cause === 'page_http_status'
            ? `The page returned ${pageStatus ?? 'an error'} when we loaded it.`
            : cause === 'browserless_timeout'
              ? 'The page took too long to load.'
              : cause === 'ssrf_blocked'
                ? "This page URL can't be rendered."
                : cause === 'not_configured'
                  ? "Screenshot rendering isn't set up on this installation."
                  : cause === 'storage_write_failed'
                    ? "The capture couldn't be stored."
                    : "The latest capture couldn't be completed."
    return `${reason} ${isUsableCapture(capture) ? 'The previous capture is still available.' : 'There is no image for this day.'}`
}

export function PageHistoryTile({
    capture,
    selected,
    disabledReason,
    onSelect,
}: {
    capture: HeatmapScreenshotHistoryItemApi
    selected: boolean
    disabledReason?: string | null
    onSelect: () => void
}): JSX.Element {
    const [failedThumbnailUrl, setFailedThumbnailUrl] = useState<string | null>(null)
    const pending = !!capture.latest_request && ['queued', 'running'].includes(capture.latest_request.state)
    const failed = capture.latest_request?.state === 'failed' || capture.status === 'failed'
    const usable = isUsableCapture(capture)
    const day = dayjs(capture.captured_on)
    const capturedTime = formatCaptureTime(capture)
    const status = pending
        ? usable
            ? 'Updating'
            : 'Capturing'
        : failed
          ? usable
              ? 'Previous image kept'
              : 'Failed'
          : !usable
            ? 'Unavailable'
            : (capturedTime ?? 'Captured')
    const details = pending
        ? usable
            ? 'A new capture is in progress. You can view the previous screenshot.'
            : 'A capture is in progress for this day.'
        : failed
          ? describeCaptureFailure(capture)
          : !usable
            ? 'This screenshot is unavailable. Choose another capture.'
            : `${capturedTime ? `Captured at ${capturedTime} in ${capture.timezone}. ` : ''}${capture.width}px screen width.${capture.trigger === 'manual' ? ' Requested capture.' : ''}`

    return (
        <LemonButton
            type="secondary"
            fullWidth
            active={selected}
            noPadding
            aria-pressed={selected}
            aria-label={`Inspect ${formatCaptureDay(capture.captured_on, 'long')}${selected ? ', displayed screenshot' : ''}${failed && usable ? ', previous screenshot kept' : !usable ? ', no screenshot' : ''}`}
            disabledReason={disabledReason}
            tooltip={
                <>
                    <strong>{day.format('dddd, MMMM D, YYYY')}</strong>
                    <div className="mt-1">{details}</div>
                </>
            }
            onClick={onSelect}
            data-attr="heatmap-page-history-capture"
            className={cn('min-w-0 overflow-hidden rounded', selected && 'ring-2 ring-accent')}
        >
            <div className="w-full min-w-0 font-normal">
                <div className="h-20 overflow-hidden bg-surface-secondary flex items-center justify-center">
                    {usable && capture.thumbnail_url && capture.thumbnail_url !== failedThumbnailUrl ? (
                        <img
                            src={capture.thumbnail_url}
                            onError={() => setFailedThumbnailUrl(capture.thumbnail_url)}
                            alt=""
                            loading="lazy"
                            className="w-full h-full object-cover object-top"
                        />
                    ) : pending ? (
                        <IconClock className="text-xl text-muted" />
                    ) : usable ? (
                        <IconCamera className="text-xl text-muted" />
                    ) : (
                        <IconWarning className="text-xl text-muted" />
                    )}
                </div>
                <div className="p-2 text-xs text-left">
                    <div className="flex items-center justify-between gap-1">
                        <span className="font-semibold truncate" translate="no">
                            {day.format('MMM D')}
                        </span>
                        {selected ? <IconCheck className="text-accent shrink-0" /> : null}
                    </div>
                    <div className={cn('flex items-center gap-1 mt-1', failed ? 'text-warning' : 'text-muted')}>
                        {pending ? (
                            <IconClock className="shrink-0" />
                        ) : failed ? (
                            <IconWarning className="shrink-0" />
                        ) : null}
                        <span className="truncate">{status}</span>
                    </div>
                </div>
            </div>
        </LemonButton>
    )
}
