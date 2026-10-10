import { useActions } from 'kea'
import { useId } from 'react'

import {
    Button,
    Field,
    FieldLabel,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { PropertyPickerPopover } from '../PropertyPickerPopover'
import { filtersEditorLogic } from './filtersEditorLogic'
import type { EditableFilterRowView } from './filtersEditorLogic'
import { FilterValueInput } from './FilterValueInput'
import { RemoveFilterButton } from './RemoveFilterButton'

export function FilterRow({
    insightProps,
    row,
}: {
    insightProps: InsightLogicProps
    row: EditableFilterRowView
}): JSX.Element {
    const { changeFilterOperator, changeFilterProperty, removeRow } = useActions(filtersEditorLogic)
    const operatorId = useId()

    return (
        <div className="flex items-start gap-2" data-attr="quill-insight-filters-row">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                <PropertyPickerPopover
                    insightProps={insightProps}
                    value={row.property}
                    onPick={(property) => changeFilterProperty(row.id, property)}
                    trigger={(open, toggle) => (
                        <Button
                            variant="outline"
                            aria-expanded={open}
                            onClick={toggle}
                            className="max-w-full"
                            data-attr="quill-insight-filters-property"
                        >
                            <span className="truncate">{row.label}</span>
                        </Button>
                    )}
                />
                <Field className="w-auto">
                    <FieldLabel htmlFor={operatorId} className="sr-only">
                        {`Operator for ${row.label}`}
                    </FieldLabel>
                    <Select
                        items={row.operatorOptions}
                        value={row.operator}
                        onValueChange={(operator) => {
                            if (operator) {
                                changeFilterOperator(row.id, operator)
                            }
                        }}
                    >
                        <SelectTrigger id={operatorId} data-attr="quill-insight-filters-operator">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {row.operatorOptions.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </Field>
                <FilterValueInput row={row} />
            </div>
            <RemoveFilterButton onClick={() => removeRow(row.id)} />
        </div>
    )
}
