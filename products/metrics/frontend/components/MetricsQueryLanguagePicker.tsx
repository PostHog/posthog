import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { MetricsQueryLanguage } from '~/queries/schema/schema-general'

import { METRICS_QUERY_LANGUAGE_LABELS } from './metricsQueryLanguageSwitch'

export function MetricsQueryLanguagePicker({
    value,
    onChange,
    disabledReason,
}: {
    value: MetricsQueryLanguage
    onChange: (language: MetricsQueryLanguage) => void
    disabledReason?: string | null
}): JSX.Element {
    // PromQL runs through Snuffle, which has its own flag.
    const promqlEnabled = useFeatureFlag('LOGS_METRICS_SNUFFLE_API')
    return (
        <LemonSegmentedButton
            size="small"
            value={value}
            onChange={onChange}
            data-attr="metrics-query-language"
            options={(['builder', 'promql', 'sql'] as const).map((language) => ({
                value: language,
                label: METRICS_QUERY_LANGUAGE_LABELS[language],
                disabledReason:
                    disabledReason ??
                    (language === 'promql' && !promqlEnabled && value !== 'promql'
                        ? 'PromQL is not turned on for this project'
                        : undefined),
            }))}
        />
    )
}
