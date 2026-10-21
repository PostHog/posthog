import { useEffect, useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonInput, LemonInputSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { objectsEqual } from 'lib/utils/objects'

import type { MetricsDashboardVariable, MetricsDashboardVariableSelection } from '~/queries/schema/schema-general'

import { ALL_OPTION, MAX_VALUE_LENGTH, selectionFromValues } from './metricVariables'

export function MetricVariableSelect({
    variable,
    options,
    loading,
    error,
    onChange,
    onRetry,
}: {
    variable: MetricsDashboardVariable
    options: string[]
    loading: boolean
    error: string | null
    onChange: (selection: MetricsDashboardVariableSelection | null) => void
    onRetry: () => void
}): JSX.Element {
    const label = (
        <span className="flex items-center gap-1">
            {variable.label || variable.name}
            {error && (
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={<IconWarning className="text-warning" />}
                    tooltip={<span className="ph-no-capture">{error}</span>}
                    disabledReason={loading ? 'Loading values' : undefined}
                    onClick={onRetry}
                    data-attr="dashboard-metric-variable-retry"
                />
            )}
        </span>
    )

    return (
        // Values come from queries over customer data, so copying one captures no text.
        <div className="ph-no-capture" data-attr="dashboard-metric-variable">
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
                        onRetry={onRetry}
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
            maxLength={MAX_VALUE_LENGTH}
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
    onRetry,
}: {
    variable: MetricsDashboardVariable
    options: string[]
    loading: boolean
    error: string | null
    onChange: (selection: MetricsDashboardVariableSelection | null) => void
    onRetry: () => void
}): JSX.Element {
    const isAll = !!(variable.current?.all && variable.includeAll)
    const savedValues = isAll ? (variable.multi ? options : [ALL_OPTION]) : (variable.current?.values ?? [])
    // A multi-select keeps its values here while the list is open, so that each click does not refresh the tiles.
    const [pending, setPending] = useState<string[] | null>(null)
    // New options, such as after a parent changes, drop the picks that are no longer options.
    useEffect(() => setPending((current) => current && current.filter((value) => options.includes(value))), [options])
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
                // The list renders outside the select, so it needs its own exclusion from autocapture.
                <div className="ph-no-capture flex flex-col items-start gap-1 p-1 max-w-80">
                    <p className="text-secondary italic m-0">{error ?? 'No values'}</p>
                    {error && (
                        <LemonButton
                            size="small"
                            type="secondary"
                            disabledReason={loading ? 'Loading values' : undefined}
                            onClick={onRetry}
                        >
                            Try again
                        </LemonButton>
                    )}
                </div>
            }
            onChange={(values) => (variable.multi ? setPending(values) : commit(values))}
            onBlur={() => pending && commit(pending)}
        />
    )
}
