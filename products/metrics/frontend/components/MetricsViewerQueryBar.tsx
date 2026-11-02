import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { type MetricsQueryLanguage } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { MetricsDateRangeFilter } from './MetricsDateRangeFilter'
import { MetricsIntervalPicker } from './MetricsIntervalPicker'
import { metricsQueryForLanguageSwitch, runMetricsQueryDraft } from './metricsQueryDraft'
import { MetricsQueryLanguagePicker } from './MetricsQueryLanguagePicker'
import { switchMetricsQueryLanguage } from './metricsQueryLanguageSwitch'
import { MetricsQueryTextEditor } from './MetricsQueryTextEditor'
import { MetricsRefreshButton } from './MetricsRefreshButton'
import { MetricsSeriesBuilder } from './MetricsSeriesBuilder'
import { metricsViewerLogic } from './metricsViewerLogic'

/** The viewer's query: the language and time controls, then the series or the PromQL/SQL editor. */
export function MetricsViewerQueryBar(): JSX.Element {
    const logic = useMountedLogic(metricsViewerLogic)
    const { language, interval, queryDraft, queryLoading, noQueryReason } = useValues(logic)
    const { setInterval, fetchQueryResults, applyQuery } = useActions(logic)
    const languagesEnabled = useFeatureFlag('METRICS_QUERY_LANGUAGES')
    const disabledReason = getAccessControlDisabledReason(AccessControlResourceType.Metrics, AccessControlLevel.Viewer)

    const runQueryText = (): void => runMetricsQueryDraft(logic, () => fetchQueryResults({}))
    const switchLanguage = (to: MetricsQueryLanguage): void =>
        switchMetricsQueryLanguage(metricsQueryForLanguageSwitch(logic), to, applyQuery)

    return (
        <>
            <div className="flex flex-wrap items-center justify-between gap-2">
                {languagesEnabled ? (
                    <MetricsQueryLanguagePicker
                        value={language}
                        onChange={switchLanguage}
                        disabledReason={disabledReason}
                    />
                ) : (
                    <span />
                )}
                <div className="flex flex-wrap items-center gap-2">
                    <MetricsDateRangeFilter disabledReason={disabledReason} />
                    <MetricsIntervalPicker value={interval} onChange={setInterval} disabledReason={disabledReason} />
                    <MetricsRefreshButton disabledReason={disabledReason} noQueryReason={noQueryReason} />
                </div>
            </div>
            {language === 'builder' ? (
                <MetricsSeriesBuilder dataAttrPrefix="metrics-viewer" disabledReason={disabledReason} />
            ) : (
                <div className="flex items-start gap-2">
                    <div className="flex-1 min-w-0">
                        <MetricsQueryTextEditor
                            language={language}
                            disabledReason={disabledReason}
                            onRun={runQueryText}
                        />
                    </div>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={runQueryText}
                        loading={queryLoading}
                        disabledReason={disabledReason ?? (queryDraft.trim() ? undefined : 'Write a query first')}
                        data-attr={`metrics-query-editor-run-${language}`}
                    >
                        Run
                    </LemonButton>
                </div>
            )}
        </>
    )
}
