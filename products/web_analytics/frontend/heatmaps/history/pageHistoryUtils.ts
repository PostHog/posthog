import type { HeatmapDateRangeOverride } from 'lib/components/heatmaps/heatmapDataLogic'
import { dayjs } from 'lib/dayjs'

import type { HeatmapScreenshotHistoryItemApi } from 'products/web_analytics/frontend/generated/api.schemas'

export function formatCaptureDay(day: string, style: 'short' | 'long' = 'short'): string {
    return dayjs(day).format(style === 'long' ? 'MMMM D, YYYY' : 'MMM D, YYYY')
}

export function formatCaptureTime(capture: HeatmapScreenshotHistoryItemApi): string | null {
    return capture.captured_at ? dayjs(capture.captured_at).tz(capture.timezone).format('HH:mm') : null
}

export function formatHistoryDateRange(range: Pick<HeatmapDateRangeOverride, 'date_from' | 'date_to'>): string {
    const from = dayjs(range.date_from)
    const to = dayjs(range.date_to)
    return from.isSame(to, 'day')
        ? formatCaptureDay(range.date_from)
        : `${from.format(from.year() === to.year() ? 'MMM D' : 'MMM D, YYYY')} to ${formatCaptureDay(range.date_to)}`
}

export function formatCaptureTimestamp(capture: HeatmapScreenshotHistoryItemApi): string {
    const time = formatCaptureTime(capture)
    return `${formatCaptureDay(capture.captured_on)}${time ? ` at ${time}` : ''} ${capture.timezone}`
}
