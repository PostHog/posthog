import { useEffect, useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonInput, LemonInputSelect, Tooltip } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { objectsEqual } from 'lib/utils/objects'

import type { MetricsDashboardVariable, MetricsDashboardVariableSelection } from '~/queries/schema/schema-general'

import { ALL_OPTION, selectionFromValues } from './metricVariables'

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
    const label = (
        <span className="flex items-center gap-1">
            {variable.label || variable.name}
            {error && (
                <Tooltip title={error}>
                    <IconWarning className="text-warning" />
                </Tooltip>
            )}
        </span>
    )

    return (
        <div data-attr="dashboard-metric-variable">
            <LemonField.Pure label={label} className="gap-0">
                {variable.source === 'textbox' ? (
                    <MetricVariableTextInput variable={variable} onChange={onChange} />
                ) : (
                    <MetricVariableOptionsSelect
                        variable={variable}
                        options={options}
                        loading={loading}
                        error={error}
                        onChange={onChange}
                    />
                )}
            </LemonField.Pure>
        </div>
    )
}

function MetricVariableTextInput({
    variable,
    onChange,
}: {
    variable: MetricsDashboardVariable
    onChange: (selection: MetricsDashboardVariableSelection | null) => void
}): JSX.Element {
    const saved = variable.current?.values[0] ?? ''
    const [text, setText] = useState(saved)
    useEffect(() => setText(saved), [saved])
    // Each change refreshes every tile, so the value is applied when the user leaves the input or presses Enter.
    const commit = (): void => {
        if (text !== saved) {
            onChange(text ? { values: [text] } : null)
        }
    }

    return (
        <LemonInput
            size="small"
            className="w-40"
            value={text}
            placeholder="Enter a value"
            onChange={setText}
            onBlur={commit}
            onPressEnter={commit}
        />
    )
}

function MetricVariableOptionsSelect({
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
    const isAll = !!(variable.current?.all && variable.includeAll)
    const savedValues = isAll ? (variable.multi ? options : [ALL_OPTION]) : (variable.current?.values ?? [])
    // A multi-select keeps its values here while the list is open, so that each click does not refresh the tiles.
    const [pending, setPending] = useState<string[] | null>(null)
    const commit = (values: string[]): void => {
        setPending(null)
        const selection = selectionFromValues(variable, values, options)
        if (!objectsEqual(selection, variable.current ?? null)) {
            onChange(selection)
        }
    }

    return (
        <LemonInputSelect
            size="small"
            className="min-w-32 max-w-80"
            mode={variable.multi ? 'multiple' : 'single'}
            displayMode={variable.multi ? 'count' : undefined}
            bulkActions={variable.multi ? 'select-and-clear-all' : undefined}
            loading={loading}
            value={pending ?? savedValues}
            placeholder={loading ? 'Loading values' : 'Select a value'}
            options={[
                ...(variable.includeAll && !variable.multi ? [{ key: ALL_OPTION, label: 'All' }] : []),
                ...options.map((option) => ({ key: option, label: option })),
            ]}
            emptyStateComponent={
                <p className="text-secondary italic p-1 max-w-80">
                    {error ?? 'No values. Check the variable query in the variable settings, or the date range.'}
                </p>
            }
            onChange={(values) => (variable.multi ? setPending(values) : commit(values))}
            onBlur={() => pending && commit(pending)}
        />
    )
}
