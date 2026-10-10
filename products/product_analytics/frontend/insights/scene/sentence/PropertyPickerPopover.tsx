import { useActions, useValues } from 'kea'
import { useId, useMemo, useRef } from 'react'
import type { MouseEvent } from 'react'

import {
    Button,
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    InputGroupAddon,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Skeleton,
    Spinner,
    Text,
    cn,
} from '@posthog/quill'

import type { InsightLogicProps, PropertyType } from '~/types'

import { PROPERTY_PICKER_GROUP_LIMIT, propertyPickerLogic } from './propertyPickerLogic'
import type { PropertyPickerGroup } from './propertyPickerLogic'

export interface PickedProperty {
    key: string
    type: 'event' | 'person' | 'session' | 'group'
    groupTypeIndex?: number
    label: string
    propertyType?: PropertyType
}

export interface PropertyPickerPopoverProps {
    insightProps: InsightLogicProps
    value?: { key: string; type: string } | null
    numericOnly?: boolean
    onPick: (property: PickedProperty) => void
    trigger: (open: boolean, toggle: () => void) => JSX.Element
}

function isSameProperty(item: PickedProperty, selected: PickedProperty): boolean {
    return item.key === selected.key && item.type === selected.type
}

function closeLandedOn(event: Event): EventTarget | null {
    return ('relatedTarget' in event ? (event as FocusEvent).relatedTarget : null) ?? event.target
}

export function PropertyPickerPopover({
    insightProps,
    value,
    numericOnly,
    onPick,
    trigger,
}: PropertyPickerPopoverProps): JSX.Element {
    const pickerId = useId()
    const triggerWrapperRef = useRef<HTMLSpanElement>(null)
    const logic = propertyPickerLogic({ pickerId, insightProps, numericOnly })
    const { isOpen, search, status, visibleGroups, isStale } = useValues(logic)
    const { openPicker, closePicker, setSearch, loadProperties } = useActions(logic)

    const selectedKey = value?.key
    const selectedType = value?.type
    const selected = useMemo(
        (): PickedProperty | null =>
            selectedKey === undefined || selectedType === undefined
                ? null
                : { key: selectedKey, type: selectedType as PickedProperty['type'], label: selectedKey },
        [selectedKey, selectedType]
    )

    const searchText = search.trim()

    return (
        <>
            {/* The wrapper has no box of its own, so the popup anchors to the trigger element inside it. */}
            <span ref={triggerWrapperRef} className="contents">
                {trigger(isOpen, () => (isOpen ? closePicker() : openPicker()))}
            </span>
            <Combobox<PickedProperty>
                items={visibleGroups}
                filter={null}
                autoHighlight
                value={selected}
                isItemEqualToValue={isSameProperty}
                onValueChange={(picked, details) => {
                    if (!picked || isStale) {
                        details.cancel()
                        return
                    }
                    onPick(picked)
                }}
                inputValue={search}
                onInputValueChange={(next) => setSearch(next)}
                open={isOpen}
                onOpenChange={(nextOpen, details) => {
                    if (nextOpen) {
                        openPicker()
                        return
                    }
                    const landedOn = closeLandedOn(details.event)
                    // A press on the trigger closes the picker through the trigger's own toggle.
                    if (landedOn instanceof Node && triggerWrapperRef.current?.contains(landedOn)) {
                        details.cancel()
                        return
                    }
                    closePicker()
                }}
            >
                <ComboboxContent
                    anchor={() => triggerWrapperRef.current?.firstElementChild ?? null}
                    className="w-80"
                    aria-busy={status === 'loading' || isStale}
                >
                    <ComboboxInput
                        placeholder="Search properties"
                        aria-label="Search properties"
                        showTrigger={false}
                        data-attr="quill-insight-property-picker-search"
                    >
                        {status === 'ready' && isStale && (
                            <InputGroupAddon align="inline-end">
                                <Spinner />
                            </InputGroupAddon>
                        )}
                    </ComboboxInput>
                    {status === 'loading' && (
                        <div className="flex flex-col gap-2 p-2" role="status" aria-label="Loading properties">
                            <Skeleton className="h-4 w-24" />
                            <Skeleton className="h-4 w-56" />
                            <Skeleton className="h-4 w-44" />
                            <Skeleton className="h-4 w-52" />
                            <Skeleton className="h-4 w-40" />
                        </div>
                    )}
                    {status === 'failed' && (
                        <div className="p-1">
                            <Item size="xs" tone="destructive" role="alert">
                                <ItemContent>
                                    <ItemTitle>Couldn't load properties</ItemTitle>
                                </ItemContent>
                                <ItemActions>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onMouseDown={(event: MouseEvent) => event.preventDefault()}
                                        onClick={() => loadProperties(false)}
                                        data-attr="quill-insight-property-picker-retry"
                                    >
                                        Try again
                                    </Button>
                                </ItemActions>
                            </Item>
                        </div>
                    )}
                    <ComboboxEmpty className="h-auto min-h-7 py-0.5 whitespace-normal">
                        {status !== 'empty'
                            ? null
                            : searchText
                              ? `No properties match "${searchText}". Try a different search.`
                              : numericOnly
                                ? 'No numeric properties found.'
                                : 'No properties found.'}
                    </ComboboxEmpty>
                    <ComboboxList className={cn(isStale && 'pointer-events-none opacity-50')}>
                        {(group: PropertyPickerGroup) => (
                            <ComboboxGroup key={group.value} items={group.items}>
                                <ComboboxLabel>{group.label}</ComboboxLabel>
                                <ComboboxCollection>
                                    {(item: PickedProperty) => (
                                        <ComboboxItem
                                            key={`${group.value}:${item.key}`}
                                            value={item}
                                            title={item.label === item.key ? item.key : `${item.label} (${item.key})`}
                                            data-attr="quill-insight-property-picker-row"
                                        >
                                            <span className="min-w-0 truncate">{item.label}</span>
                                            {item.label !== item.key && (
                                                <Text
                                                    size="xs"
                                                    variant="muted"
                                                    render={<span />}
                                                    className="min-w-0 truncate font-mono"
                                                    translate="no"
                                                >
                                                    {item.key}
                                                </Text>
                                            )}
                                        </ComboboxItem>
                                    )}
                                </ComboboxCollection>
                                {group.total > group.items.length && (
                                    <Item size="xs">
                                        <ItemContent>
                                            <ItemDescription>
                                                {`Showing the first ${PROPERTY_PICKER_GROUP_LIMIT} ${group.label.toLowerCase()}. Search to find more.`}
                                            </ItemDescription>
                                        </ItemContent>
                                    </Item>
                                )}
                            </ComboboxGroup>
                        )}
                    </ComboboxList>
                </ComboboxContent>
            </Combobox>
        </>
    )
}
