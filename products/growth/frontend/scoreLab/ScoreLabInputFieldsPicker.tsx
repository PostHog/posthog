import { useValues } from 'kea'

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
    Item,
    ItemContent,
    ItemDescription,
    ItemTitle,
    useComboboxAnchor,
} from 'lib/ui/quill'

import type { InputFieldApi, InputFieldsEnumApi } from '../generated/api.schemas'
import { scoreLabLogic } from './scoreLabLogic'

interface ScoreLabInputFieldsPickerProps {
    value: InputFieldsEnumApi[]
    onChange: (next: InputFieldsEnumApi[]) => void
    /** True while a different input source (the HogQL query) is the one actually sent to the backend. */
    disabled?: boolean
}

export function ScoreLabInputFieldsPicker({
    value,
    onChange,
    disabled = false,
}: ScoreLabInputFieldsPickerProps): JSX.Element {
    // Served by the API, which is also what enforces the allow-list on save - a mirrored copy here
    // would offer paths the backend rejects.
    const { inputFieldOptions } = useValues(scoreLabLogic)
    const selectedPaths: string[] = value
    const selected = inputFieldOptions.filter((option: InputFieldApi) => selectedPaths.includes(option.value))

    return (
        <Combobox
            multiple
            autoHighlight
            disabled={disabled}
            items={inputFieldOptions}
            itemToStringValue={(option: InputFieldApi) => option.label}
            value={selected}
            onValueChange={(next: InputFieldApi[]) =>
                onChange(next.map((option) => option.value as InputFieldsEnumApi))
            }
        >
            <ScoreLabInputFieldsPickerBody disabled={disabled} />
        </Combobox>
    )
}

function ScoreLabInputFieldsPickerBody({ disabled }: { disabled: boolean }): JSX.Element {
    const anchor = useComboboxAnchor()
    return (
        <>
            {/* The fill carries the disabled affordance, not opacity alone. Quill's own border on this
                container is stripped by a build-wide packaging bug (border-width computes to 0), so
                dimming an unfilled, borderless box was invisible. A filled surface still reads as an
                inactive control once that border comes back. */}
            <ComboboxChips
                ref={anchor}
                className={disabled ? 'pointer-events-none bg-surface-secondary opacity-80' : undefined}
            >
                <ComboboxValue>
                    {(values: InputFieldApi[]) => (
                        <>
                            {values.map((option) => (
                                <ComboboxChip key={option.value} title={option.label}>
                                    {option.label}
                                </ComboboxChip>
                            ))}
                            <ComboboxChipsInput placeholder="Search payload fields..." disabled={disabled} />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>No matching fields</ComboboxEmpty>
                <ComboboxList>
                    {(option: InputFieldApi) => (
                        <ComboboxItem key={option.value} value={option} className="h-auto">
                            <Item size="xs" className="p-0">
                                <ItemContent variant="menuItem">
                                    <ItemTitle>{option.label}</ItemTitle>
                                    <ItemDescription>{option.type}</ItemDescription>
                                </ItemContent>
                            </Item>
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}
