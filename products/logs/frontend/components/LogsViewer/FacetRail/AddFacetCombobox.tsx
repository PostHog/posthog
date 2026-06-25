import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from 'lib/ui/quill'

interface AddFacetComboboxProps {
    /** Resource-attribute keys the user can add (already excludes curated + already-added). */
    availableKeys: string[]
    onAdd: (key: string) => void
    onClose: () => void
}

/** Search-and-pick a resource-attribute key to add as a custom facet. Picking one adds it and closes. */
export function AddFacetCombobox({ availableKeys, onAdd, onClose }: AddFacetComboboxProps): JSX.Element {
    return (
        <Combobox
            items={availableKeys}
            autoHighlight
            defaultOpen
            value={null}
            onValueChange={(key: string | null) => {
                if (key) {
                    onAdd(key)
                }
                onClose()
            }}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    onClose()
                }
            }}
        >
            <ComboboxInput placeholder="Add facet…" autoFocus data-attr="logs-facet-rail-add-input" />
            <ComboboxContent>
                <ComboboxEmpty>No more attributes to add</ComboboxEmpty>
                <ComboboxList>
                    {(item: string) => (
                        <ComboboxItem key={item} value={item} title={item}>
                            {item}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
