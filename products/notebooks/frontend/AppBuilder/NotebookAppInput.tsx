import { useContext, useId } from 'react'

import { LemonBanner, LemonButton, LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import type { NotebookVariable, NotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'
import { coerceNotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'

import type { NotebookAppBlockApi } from '../generated/api.schemas'
import { NotebookVariableListInput } from '../NotebookVariableListInput'
import { dropdownOptions, NotebookAppQueryChoicesContext, type QueryChoiceResult } from './notebookAppChoices'

type InputProps = {
    variable: NotebookVariable
    disabled: boolean
    onChange: (value: NotebookVariableValue) => void
}

export function NotebookAppInput({
    block,
    cell,
    variable,
    disabled,
    onChange,
}: Omit<InputProps, 'variable'> & {
    cell?: NotebookBlockNode
    block: NotebookAppBlockApi
    variable?: NotebookVariable
}): JSX.Element {
    const id = useId()
    const getChoices = useContext(NotebookAppQueryChoicesContext)
    if (!variable) {
        return <LemonBanner type="warning">Choose an existing notebook variable in component settings.</LemonBanner>
    }
    const label = block.title || variable.name
    const choices = block.input_kind === 'query_select' ? getChoices(cell, block.option_column ?? '') : undefined
    const options = dropdownOptions(block, choices)
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
                    maskValues={block.input_kind === 'query_select'}
                    disabled={disabled}
                    onChange={onChange}
                />
            ) : options ? (
                <LemonSelect
                    id={id}
                    fullWidth
                    value={String(variable.value ?? '')}
                    disabled={disabled}
                    className={block.input_kind === 'query_select' ? 'ph-no-capture' : undefined}
                    menu={block.input_kind === 'query_select' ? { className: 'ph-no-capture' } : undefined}
                    options={options.map((value) => ({ value, label: value }))}
                    onChange={(value) => onChange(coerceNotebookVariableValue(variable.type, value))}
                />
            ) : (
                <VariableControl id={id} block={block} variable={variable} disabled={disabled} onChange={onChange} />
            )}
            {block.input_kind === 'query_select' && (
                <QueryChoiceStatus choices={choices} variable={variable} disabled={disabled} onChange={onChange} />
            )}
            <span className="text-xs text-secondary">{`Notebook variable: ${variable.name}`}</span>
        </div>
    )
}

function VariableControl({
    id,
    block,
    variable,
    disabled,
    onChange,
}: InputProps & { id: string; block: NotebookAppBlockApi }): JSX.Element {
    if (block.input_kind === 'slider' && variable.type === 'number') {
        const sliderValue = variable.value ?? 0
        return (
            <div className="flex items-center gap-3">
                <input
                    id={id}
                    aria-label={block.title || variable.name}
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
        )
    }
    return <AutomaticVariableControl id={id} variable={variable} disabled={disabled} onChange={onChange} />
}

function AutomaticVariableControl({ id, variable, disabled, onChange }: InputProps & { id: string }): JSX.Element {
    const textValue = String(variable.value ?? '')
    return variable.type === 'boolean' ? (
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
    )
}

function QueryChoiceStatus({
    choices,
    variable,
    disabled,
    onChange,
}: InputProps & { choices?: QueryChoiceResult }): JSX.Element {
    if (choices === 'unavailable') {
        return (
            <small role="status">
                Could not load the saved choices. Refresh results to run the options query again.
            </small>
        )
    }
    if (!choices) {
        return <small role="status">Choices will be available when the options query has a result.</small>
    }
    const textValue = String(variable.value ?? '')
    const selection = Array.isArray(variable.value) ? variable.value : textValue ? [textValue] : []
    const missingChoice = !choices.partial && selection.some((value) => !choices.values.includes(value))
    return (
        <>
            {!choices.values.length && <small role="status">No choices match the current inputs.</small>}
            {choices.partial && (
                <small>
                    Showing choices from the first available rows. Refine the options query for more specific choices.
                </small>
            )}
            {missingChoice && (
                <div className="flex items-center gap-2">
                    <small>The current selection is outside these choices.</small>
                    <LemonButton
                        size="xsmall"
                        disabled={disabled}
                        onClick={() => onChange(variable.type === 'list' ? [] : null)}
                    >
                        Clear selection
                    </LemonButton>
                </div>
            )}
        </>
    )
}
