import { useActions } from 'kea'
import { useId } from 'react'

import { Button, Field, FieldDescription, FieldLabel } from '@posthog/quill'

import { filtersEditorLogic } from './filtersEditorLogic'
import type { EditableFilterRowView } from './filtersEditorLogic'
import { FilterValueChips } from './FilterValueChips'
import { FilterValueText } from './FilterValueText'

export function FilterValueInput({ row }: { row: EditableFilterRowView }): JSX.Element | null {
    const { searchFilterValues } = useActions(filtersEditorLogic)
    const inputId = useId()

    if (row.valueKind === 'none') {
        return null
    }

    return (
        <Field className="w-auto min-w-40 flex-1">
            <FieldLabel htmlFor={inputId} className="sr-only">
                {`Value for ${row.label}`}
            </FieldLabel>
            {row.valueKind === 'many' ? (
                <FilterValueChips row={row} inputId={inputId} />
            ) : (
                <FilterValueText row={row} inputId={inputId} />
            )}
            {row.suggestionsStatus === 'error' && (
                <FieldDescription>
                    <span>Couldn't load suggestions. You can still type a value. </span>
                    <Button
                        variant="link"
                        size="xs"
                        onClick={() => searchFilterValues(row.id, row.search)}
                        data-attr="quill-insight-filters-retry-suggestions"
                    >
                        Try again
                    </Button>
                </FieldDescription>
            )}
        </Field>
    )
}
