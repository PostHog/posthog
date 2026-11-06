import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { type MetricsQuery, type MetricsQueryLanguage } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { MetricsChartSettings } from './MetricsChartSettings'
import { MetricsDateRangeFilter } from './MetricsDateRangeFilter'
import { MetricsDisplayTypeSelect } from './MetricsDisplayTypeSelect'
import { MetricsIntervalPicker } from './MetricsIntervalPicker'
import { metricsQueryForLanguageSwitch, runMetricsQueryDraft } from './metricsQueryDraft'
import { MetricsQueryLanguagePicker } from './MetricsQueryLanguagePicker'
import { MetricsQueryTextEditor } from './MetricsQueryTextEditor'
import { MetricsSeriesBuilder } from './MetricsSeriesBuilder'
import { metricsViewerLogic } from './metricsViewerLogic'

export interface MetricsQueryControlsProps {
    /** Prefix of the `data-attr` of each control, so each surface keeps its own analytics names. */
    dataAttrPrefix: 'metrics-query-editor'
    /** The query a language switch converts while the builder has no metric yet. */
    fallbackQuery?: MetricsQuery
    /** Shows the builder / PromQL / SQL switch. Gets the query as it is now, including an unrun draft. */
    onSwitchLanguage?: (current: MetricsQuery, to: MetricsQueryLanguage) => void
    /** Runs the current PromQL or SQL query again when Run is pressed without a change, as after a failure. */
    onRerun?: () => void
    /** Offers the heatmap display, which saves a histogram query instead of a time series. */
    heatmap?: { eligible: boolean }
}

/** The metrics query controls of the metrics insight editor. */
export function MetricsQueryControls({
    dataAttrPrefix,
    fallbackQuery,
    onSwitchLanguage,
    onRerun,
    heatmap,
}: MetricsQueryControlsProps): JSX.Element {
    const { language, queryDraft, interval } = useValues(metricsViewerLogic)
    const { setInterval } = useActions(metricsViewerLogic)
    const logic = useMountedLogic(metricsViewerLogic)
    const disabledReason = getAccessControlDisabledReason(AccessControlResourceType.Metrics, AccessControlLevel.Viewer)

    const runQuery = (): void => runMetricsQueryDraft(logic, onRerun)
    const switchLanguage = (to: MetricsQueryLanguage): void =>
        onSwitchLanguage?.(metricsQueryForLanguageSwitch(logic, fallbackQuery), to)

    const dateControls = (
        <div className="flex flex-wrap items-center gap-2">
            <MetricsDateRangeFilter disabledReason={disabledReason} />
            <MetricsIntervalPicker value={interval} onChange={setInterval} disabledReason={disabledReason} />
        </div>
    )

    const builderControls = <MetricsSeriesBuilder dataAttrPrefix={dataAttrPrefix} disabledReason={disabledReason} />

    return (
        <div className="flex flex-col gap-2" data-attr={dataAttrPrefix}>
            {onSwitchLanguage ? (
                <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <MetricsQueryLanguagePicker
                            value={language}
                            onChange={switchLanguage}
                            disabledReason={disabledReason}
                        />
                        {dateControls}
                    </div>
                    {language === 'builder' ? (
                        builderControls
                    ) : (
                        <MetricsQueryTextEditor language={language} disabledReason={disabledReason} onRun={runQuery} />
                    )}
                </>
            ) : (
                <div className="flex flex-wrap items-start gap-2 justify-between">
                    {builderControls}
                    {dateControls}
                </div>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <MetricsDisplayTypeSelect
                        dataAttrPrefix={dataAttrPrefix}
                        heatmap={heatmap}
                        disabledReason={disabledReason}
                    />
                    <MetricsChartSettings />
                </div>
                {language !== 'builder' && (
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={runQuery}
                        disabledReason={disabledReason ?? (queryDraft.trim() ? undefined : 'Write a query first')}
                        data-attr={`metrics-query-editor-run-${language}`}
                    >
                        Run
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
