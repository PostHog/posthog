import { useIsFocused } from 'expo-router'
import { useEffect, useMemo, useRef } from 'react'
import type { LayoutChangeEvent } from 'react-native'
import { type SharedValue, useSharedValue } from 'react-native-reanimated'

import { type AnalyticsEvent, track } from '@/lib/analytics'

import { useAppActive } from '../handoff/useTaskRun'

/** The bottom padding and the action bar cover the last lines, so the end counts as reached this close to it. */
const END_SLACK_PX = 160

export interface ReportReadTracking {
    maxScrollY: SharedValue<number>
    onLayout: (event: LayoutChangeEvent) => void
    onContentSizeChange: (width: number, height: number) => void
}

/** The report screen and the full report send the same read properties under their own event names. */
export type ReadEvent = Extract<AnalyticsEvent, 'mobile_report_read' | 'mobile_report_details_read'>

/**
 * Sends one `event` when the screen body unmounts, which happens on Back and, on the report screen, on Prev/Next.
 * `dwell_s` counts only the time the screen had focus with the app in the foreground, so time in task chat or in
 * the background is left out.
 */
export function useReportReadTracking(reportId: string, event: ReadEvent = 'mobile_report_read'): ReportReadTracking {
    const maxScrollY = useSharedValue(0)
    const viewportHeight = useRef(0)
    const contentHeight = useRef(0)
    const visibleMs = useRef(0)
    const visibleSince = useRef<number | null>(null)
    const focused = useIsFocused()
    const appActive = useAppActive()
    const visible = focused && appActive

    useEffect(() => {
        if (!visible) {
            return undefined
        }
        visibleSince.current = Date.now()
        return () => {
            if (visibleSince.current !== null) {
                visibleMs.current += Date.now() - visibleSince.current
                visibleSince.current = null
            }
        }
    }, [visible])

    useEffect(
        () => () => {
            const openMs = visibleSince.current !== null ? Date.now() - visibleSince.current : 0
            const scrolledToEnd = maxScrollY.value + viewportHeight.current >= contentHeight.current - END_SLACK_PX
            track(event, {
                report_id: reportId,
                dwell_s: Math.round((visibleMs.current + openMs) / 1000),
                scrolled_to_end: scrolledToEnd,
            })
        },
        [reportId, event, maxScrollY]
    )

    return useMemo(
        () => ({
            maxScrollY,
            onLayout: (event: LayoutChangeEvent) => {
                viewportHeight.current = event.nativeEvent.layout.height
            },
            onContentSizeChange: (_width: number, height: number) => {
                contentHeight.current = height
            },
        }),
        [maxScrollY]
    )
}
