import { useState } from 'react'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import {
    MAX_NOTEBOOK_VARIABLE_LIST_ITEMS,
    MAX_NOTEBOOK_VARIABLE_VALUE_CHARS,
    type NotebookVariableValue,
} from 'scenes/notebooks/Notebook/notebookVariables'

export function NotebookVariableListInput({
    id,
    value,
    options,
    disabled,
    size,
    onChange,
}: {
    id: string
    value: NotebookVariableValue
    options?: string[]
    disabled: boolean
    size?: 'small'
    onChange: (value: string[]) => void
}): JSX.Element {
    const [error, setError] = useState('')
    return (
        <div>
            <LemonInputSelect
                id={id}
                mode="multiple"
                fullWidth
                size={size}
                disabled={disabled}
                value={Array.isArray(value) ? value : []}
                options={options && [...new Set(options.filter(Boolean))].map((key) => ({ key, label: key }))}
                allowCustomValues={options === undefined}
                disableCommaSplitting
                placeholder={options ? 'Select values' : 'Add a value'}
                limit={MAX_NOTEBOOK_VARIABLE_LIST_ITEMS}
                bulkActions={options ? 'clear-all' : undefined}
                onChange={(items) => {
                    if (
                        items.length > MAX_NOTEBOOK_VARIABLE_LIST_ITEMS ||
                        items.reduce((total, item) => total + Array.from(item).length, 0) >
                            MAX_NOTEBOOK_VARIABLE_VALUE_CHARS
                    ) {
                        setError(
                            `Use up to ${MAX_NOTEBOOK_VARIABLE_LIST_ITEMS} items and ${MAX_NOTEBOOK_VARIABLE_VALUE_CHARS} characters in total.`
                        )
                        return
                    }
                    setError('')
                    onChange(items)
                }}
            />
            {error && (
                <span role="alert" className="text-danger text-xs">
                    {error}
                </span>
            )}
        </div>
    )
}
