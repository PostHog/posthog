import { IconWarning } from '@posthog/icons'
import { LemonInput, LemonInputSelect, Tooltip } from '@posthog/lemon-ui'

import type { MetricsDashboardVariable, MetricsDashboardVariableSelection } from '~/queries/schema/schema-general'

import { ALL_OPTION } from './metricVariables'

/** One dashboard variable: a select of its options, or a text input for a free-text variable. */
export function MetricVariableSelect({
    variable,
    options,
    loading,
    error,
    onChange,
}: {
    variable: MetricsDashboardVariable
    options: string[]
    loading: boolean
    error: string | null
    onChange: (selection: MetricsDashboardVariableSelection | null) => void
}): JSX.Element {
    const label = variable.label || variable.name
    const isAll = !!(variable.current?.all && variable.includeAll)

    return (
        <div className="flex flex-col gap-1 min-w-0" data-attr="dashboard-metric-variable">
            <span className="flex items-center gap-1 text-xs font-semibold text-secondary">
                {label}
                {error && (
                    <Tooltip title={error}>
                        <IconWarning className="text-warning" />
                    </Tooltip>
                )}
            </span>
            {variable.source === 'textbox' ? (
                <LemonInput
                    size="small"
                    className="min-w-32"
                    value={variable.current?.values[0] ?? ''}
                    placeholder={`Enter ${label}`}
                    onChange={(value) => onChange(value ? { values: [value] } : null)}
                />
            ) : (
                <LemonInputSelect
                    size="small"
                    className="min-w-32 max-w-80"
                    mode={variable.multi ? 'multiple' : 'single'}
                    displayMode={variable.multi ? 'count' : undefined}
                    loading={loading}
                    value={isAll ? [ALL_OPTION] : (variable.current?.values ?? [])}
                    options={[
                        ...(variable.includeAll ? [{ key: ALL_OPTION, label: 'All' }] : []),
                        ...options.map((option) => ({ key: option, label: option })),
                    ]}
                    emptyStateComponent={
                        <p className="text-secondary italic p-1">
                            {error ?? 'No options. Check the variable query and the date range.'}
                        </p>
                    }
                    onChange={(values) => {
                        if (values.includes(ALL_OPTION) && (!isAll || values.length === 1)) {
                            onChange({ values: options, all: true })
                            return
                        }
                        const selected = values.filter((value) => value !== ALL_OPTION)
                        onChange(selected.length ? { values: selected } : null)
                    }}
                />
            )}
        </div>
    )
}
