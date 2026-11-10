import { createContext } from 'react'

import type { ReportChartApi } from 'products/signals/frontend/generated/api.schemas'

/**
 * The charts of the report on screen, by chart id. Whoever renders a report body provides it, so a
 * `chart:` reference in the summary resolves wherever the body appears, in the Inbox or on Today,
 * without that surface having to mount the Inbox detail logic.
 */
export const ReportChartsContext = createContext<ReadonlyMap<string, ReportChartApi>>(new Map())
