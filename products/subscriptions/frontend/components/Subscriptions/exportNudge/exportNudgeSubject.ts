import { ExporterFormat, InsightShortId } from '~/types'

/** What an export is of. Exports of anything else are never nudged. */
export type ExportNudgeSubject =
    | { kind: 'dashboard'; dashboardId: number }
    | { kind: 'insight'; insightShortId: InsightShortId }

// A subscription renders a PNG, so only a PNG export is worth answering with the offer of one.
// Someone taking a CSV wants the rows. The backend side of that is the PNG in
// products/exports/backend/temporal/subscriptions/activities.py.
const SUBSCRIBABLE_EXPORT_FORMATS: ExporterFormat[] = [ExporterFormat.PNG]

/**
 * Only a dashboard or a saved insight can be subscribed to, so a recording, a heatmap, a cohort, a
 * data table or a billing report has no subject. Nor does an insight exported from a surface that
 * does not pass its short id, since there would be no subscription page to send anyone to.
 */
export function exportNudgeSubjectFor(exportData: {
    export_format: ExporterFormat
    dashboard?: number | null
    insightShortId?: InsightShortId
}): ExportNudgeSubject | null {
    if (!SUBSCRIBABLE_EXPORT_FORMATS.includes(exportData.export_format)) {
        return null
    }
    if (exportData.dashboard) {
        return { kind: 'dashboard', dashboardId: exportData.dashboard }
    }
    if (exportData.insightShortId) {
        return { kind: 'insight', insightShortId: exportData.insightShortId }
    }
    return null
}
