import { useId } from 'react'

import { LemonBanner, LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import type { NotebookVariable, NotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'
import { coerceNotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'

import type { NotebookAppBlockApi } from '../generated/api.schemas'

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
    return (
        <div className="flex flex-col gap-2">
            <label htmlFor={id} className="font-semibold">
                {label}
            </label>
            {block.input_kind === 'select' ? (
                <LemonSelect
                    id={id}
                    fullWidth
                    value={String(variable.value ?? '')}
                    disabled={disabled}
                    options={(block.options ?? []).map((value) => ({ value, label: value }))}
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
                        value={Number(variable.value ?? 0)}
                        onChange={(event) => onChange(Number(event.target.value))}
                    />
                    <output htmlFor={id}>{String(variable.value ?? 0)}</output>
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
                    value={variable.value ? dayjs(String(variable.value)) : null}
                    onChange={(date) => onChange(date?.format('YYYY-MM-DD') ?? '')}
                    buttonProps={{ id, disabledReason: disabled ? 'This notebook is read-only' : undefined }}
                />
            ) : (
                <LemonInput
                    id={id}
                    value={String(variable.value ?? '')}
                    maxLength={1000}
                    disabled={disabled}
                    onChange={onChange}
                />
            )}
            <span className="text-xs text-secondary">{`Notebook variable: ${variable.name}`}</span>
        </div>
    )
}
