import { useActions } from 'kea'
import { useRef } from 'react'

import {
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
} from '@posthog/quill'

import { filtersEditorLogic } from './filtersEditorLogic'
import type { EditableFilterRowView } from './filtersEditorLogic'
import { suggestionsEmptyText } from './suggestionsEmptyText'

export function FilterValueChips({ row, inputId }: { row: EditableFilterRowView; inputId: string }): JSX.Element {
    const { changeFilterValue, searchFilterValues } = useActions(filtersEditorLogic)
    const anchorRef = useRef<HTMLDivElement>(null)

    return (
        <Combobox
            multiple
            autoHighlight
            items={row.valueOptions}
            value={row.values}
            onValueChange={(values: string[]) => changeFilterValue(row.id, values)}
            inputValue={row.search}
            onInputValueChange={(search: string) => searchFilterValues(row.id, search)}
            onOpenChange={(open: boolean) => {
                if (open) {
                    searchFilterValues(row.id, row.search)
                }
            }}
        >
            {/* ComboboxChips does not pass a ref on under React 18, so this wrapper is the popup's anchor. */}
            <div ref={anchorRef}>
                <ComboboxChips data-attr="quill-insight-filters-values">
                    <ComboboxValue>
                        {(values: string[]) => (
                            <>
                                {values.map((value) => (
                                    <ComboboxChip key={value}>{value}</ComboboxChip>
                                ))}
                                <ComboboxChipsInput
                                    id={inputId}
                                    placeholder={values.length === 0 ? row.valuePlaceholder : undefined}
                                />
                            </>
                        )}
                    </ComboboxValue>
                </ComboboxChips>
            </div>
            <ComboboxContent anchor={anchorRef}>
                <ComboboxEmpty>{suggestionsEmptyText(row.suggestionsStatus)}</ComboboxEmpty>
                <ComboboxList>
                    {(item: string) => (
                        <ComboboxItem key={item} value={item}>
                            {item}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
