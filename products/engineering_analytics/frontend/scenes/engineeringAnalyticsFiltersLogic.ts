import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import type { engineeringAnalyticsFiltersLogicType } from './engineeringAnalyticsFiltersLogicType'

// One window shared by every CI-analytics surface that's scoped by time — the Workflows tab, a single
// workflow's runs/cost page, and an author's cost tiles — so a window picked on one carries to the others
// instead of each page snapping back to its own default. 7 days balances the two needs the pages used to
// split on (-24h health vs -30d spend): long enough to read a week of spend, short enough that health still
// reads as recent. Nothing live is lost — the "is CI red now" verdict is window-independent and bucket
// granularity auto-follows the window, so narrowing to 24h still gives the live hourly view on demand.
export const SHARED_DEFAULT_DATE_FROM = '-7d'

export const engineeringAnalyticsFiltersLogic = kea<engineeringAnalyticsFiltersLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'engineeringAnalyticsFiltersLogic']),

    actions({
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
    }),

    reducers({
        dateFrom: [SHARED_DEFAULT_DATE_FROM as string | null, { setDateRange: (_, { dateFrom }) => dateFrom }],
        dateTo: [null as string | null, { setDateRange: (_, { dateTo }) => dateTo }],
    }),

    actionToUrl(({ values }) => ({
        // Encode the window in the URL so tab links and drill-down links (which preserve query params) carry
        // it, and a shared link reopens it. Replace, not push — nudging a date shouldn't stack back-history.
        // The default is omitted so a pristine URL stays clean.
        setDateRange: () => {
            const { pathname, searchParams, hashParams } = router.values.currentLocation
            const next = { ...searchParams }
            if (values.dateFrom && values.dateFrom !== SHARED_DEFAULT_DATE_FROM) {
                next.date_from = values.dateFrom
            } else {
                delete next.date_from
            }
            if (values.dateTo) {
                next.date_to = values.dateTo
            } else {
                delete next.date_to
            }
            return [pathname, next, hashParams, { replace: true }]
        },
    })),

    urlToAction(({ actions, values }) => {
        // Hydrate from the URL on any CI-analytics route — a shared link, a reload, or a drill-down link that
        // carried the params. Guarded so we only dispatch on a real change, which also breaks the actionToUrl
        // loop. '*' is safe here: the logic is only mounted while a CI-analytics scene connects it, so this
        // never fires for unrelated routes.
        const sync = (_: Record<string, string>, search: Record<string, string>): void => {
            const dateFrom = search.date_from ?? SHARED_DEFAULT_DATE_FROM
            const dateTo = search.date_to ?? null
            if (dateFrom !== values.dateFrom || dateTo !== values.dateTo) {
                actions.setDateRange(dateFrom, dateTo)
            }
        }
        return { '*': sync }
    }),
])
