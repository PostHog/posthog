import { useId } from 'react'

import { LemonBanner, LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import type { NotebookVariable, NotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'
import { coerceNotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'

import type { NotebookAppBlockApi } from '../generated/api.schemas'
import { NotebookVariableListInput } from '../NotebookVariableListInput'

export function NotebookAppInput({
    block,
    variable,
    disabled,
    onChange,
}: {
    block: NotebookAppBlockApi
    variable?: NotebookVariable
    disabled: boolean
    onChange: (value: NotebookVariableValue) => void
}): JSX.Element {
    const id = useId()
    if (!variable) {
        return <LemonBanner type="warning">Choose an existing notebook variable in component settings.</LemonBanner>
    }
    const label = block.title || variable.name
    const textValue = String(variable.value ?? '')
    const options = block.input_kind === 'select' ? (block.options ?? []) : undefined
    const sliderValue = variable.value ?? 0
    return (
        <div className="flex flex-col gap-2">
            <label htmlFor={id} className="font-semibold">
                {label}
            </label>
            {variable.type === 'list' ? (
                <NotebookVariableListInput
                    id={id}
                    value={variable.value}
                    options={options}
                    disabled={disabled}
                    onChange={onChange}
                />
            ) : options ? (
                <LemonSelect
                    id={id}
                    fullWidth
                    value={textValue}
                    disabled={disabled}
                    options={options.map((value) => ({ value, label: value }))}
                    onChange={(value) => onChange(coerceNotebookVariableValue(variable.type, value))}
                />
            ) : block.input_kind === 'slider' && variable.type === 'number' ? (
                <div className="flex items-center gap-3">
                    <input
                        id={id}
                        aria-label={label}
                        type="range"
                        className="flex-1 min-w-0"
                        disabled={disabled}
                        min={block.min ?? 0}
                        max={block.max ?? 100}
                        step={block.step ?? 1}
                        value={Number(sliderValue)}
                        onChange={(event) => onChange(Number(event.target.value))}
                    />
                    <output htmlFor={id}>{String(sliderValue)}</output>
                </div>
            ) : variable.type === 'boolean' ? (
                <LemonCheckbox
                    id={id}
                    checked={variable.value === true}
                    disabled={disabled}
                    onChange={onChange}
                    label="Enabled"
                />
            ) : variable.type === 'number' ? (
                <LemonInput
                    id={id}
                    type="number"
                    value={typeof variable.value === 'number' ? variable.value : undefined}
                    disabled={disabled}
                    onChange={(value) => onChange(value ?? null)}
                />
            ) : variable.type === 'date' ? (
                <LemonCalendarSelectInput
                    value={variable.value ? dayjs(textValue) : null}
                    onChange={(date) => onChange(date?.format('YYYY-MM-DD') ?? '')}
                    buttonProps={{ id, disabledReason: disabled ? 'This notebook is read-only' : undefined }}
                />
            ) : (
                <LemonInput id={id} value={textValue} maxLength={1000} disabled={disabled} onChange={onChange} />
            )}
            <span className="text-xs text-secondary">{`Notebook variable: ${variable.name}`}</span>
        </div>
    )
}
