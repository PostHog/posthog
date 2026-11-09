import type { BuiltLogic } from 'kea'

import { type MetricsQuery, NodeKind } from '~/queries/schema/schema-general'

import type { metricsViewerLogicType } from './metricsViewerLogic'

/** Runs a changed PromQL or SQL draft through the query node, or runs the unchanged query again, as after a failure. */
export function runMetricsQueryDraft(logic: BuiltLogic<metricsViewerLogicType>, rerun?: () => void): void {
    if (logic.values.queryTextChanged) {
        logic.actions.runQueryText()
    } else {
        rerun?.()
    }
}

/** The query a language switch converts. Read at click time, so a draft the user has not run yet still converts. */
export function metricsQueryForLanguageSwitch(
    logic: BuiltLogic<metricsViewerLogicType>,
    fallbackQuery?: MetricsQuery
): MetricsQuery {
    const { metricsQueryNode, queryDraft, language } = logic.values
    const current = metricsQueryNode ?? fallbackQuery ?? { kind: NodeKind.MetricsQuery, clauses: [] }
    return language === 'builder' ? current : { ...current, [language]: queryDraft.trim() }
}
