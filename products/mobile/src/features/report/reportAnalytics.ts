import { useMemo, useRef } from 'react'

import { ApiError, NotSignedInError } from '@/api/client'
import { missingScope } from '@/api/scopeErrors'
import { track } from '@/lib/analytics'

/** How the report screen was reached. Sent with `mobile_report_opened`, so it travels in the route as `from`. */
export type ReportOpenSource = 'inbox' | 'push' | 'adjacent' | 'deep_link'

const OPEN_SOURCES: readonly ReportOpenSource[] = ['inbox', 'push', 'adjacent', 'deep_link']

/** A deep link names no source, so a missing or unknown `from` counts as `deep_link`. */
export function reportOpenSourceParam(value: string | string[] | undefined): ReportOpenSource {
    const first = Array.isArray(value) ? value[0] : value
    return OPEN_SOURCES.find((source) => source === first) ?? 'deep_link'
}

export type ReportSheet =
    | 'handoff'
    | 'resolve'
    | 'dismiss'
    | 'assignee'
    | 'priority'
    | 'decision'
    | 'pull_request_picker'

export type SheetEntry = 'action_bar' | 'chip' | 'inbox_menu'

export type ApiErrorKind = 'scope' | 'auth' | 'forbidden' | 'not_found' | 'server' | 'network' | 'unknown'

/** A short enum for a failed request, because the error message can quote the server or name the host. */
export function apiErrorKind(error: unknown): ApiErrorKind {
    if (error instanceof NotSignedInError) {
        return 'auth'
    }
    // A missing scope is also a 403, so it must be checked before the plain 403.
    if (missingScope(error)) {
        return 'scope'
    }
    if (error instanceof ApiError) {
        if (error.status === 401) {
            return 'auth'
        }
        if (error.status === 403) {
            return 'forbidden'
        }
        if (error.status === 404) {
            return 'not_found'
        }
        return error.status >= 500 ? 'server' : 'unknown'
    }
    return error instanceof TypeError ? 'network' : 'unknown'
}

export interface SheetFunnel {
    opened: (sheet: ReportSheet, from: SheetEntry, properties?: { kind?: string }) => void
    /** Marks the open sheet as finished, so closing it after this does not count as a dismissal. */
    completed: () => void
    /** Call on every close. Sends `mobile_report_sheet_dismissed` only when the sheet closed without `completed`. */
    closed: () => void
}

/** `reportId` is undefined on surfaces outside a report, such as task chat. Those send nothing. */
export function useSheetFunnel(reportId: string | undefined): SheetFunnel {
    const open = useRef<{ sheet: ReportSheet; from: SheetEntry; reportId: string; completed: boolean } | null>(null)
    const report = useRef(reportId)
    report.current = reportId
    return useMemo(
        () => ({
            opened: (sheet, from, properties) => {
                if (!report.current) {
                    return
                }
                open.current = { sheet, from, reportId: report.current, completed: false }
                track('mobile_report_sheet_opened', { sheet, from, report_id: report.current, ...properties })
            },
            completed: () => {
                if (open.current) {
                    open.current.completed = true
                }
            },
            closed: () => {
                const sheet = open.current
                open.current = null
                if (sheet && !sheet.completed) {
                    track('mobile_report_sheet_dismissed', {
                        sheet: sheet.sheet,
                        from: sheet.from,
                        report_id: sheet.reportId,
                    })
                }
            },
        }),
        []
    )
}
