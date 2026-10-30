import { KeyboardEvent, RefObject, useEffect, useId, useMemo, useRef, useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import type { CreateActionType } from '../../hogFlowEditorLogic'
import { StepPaletteRow } from './StepPaletteRow'
import { filterPaletteItems, PaletteItem, PaletteSection } from './tileCanvasModel'
import type { CanvasCommand } from './useCanvasCommands'
import { useComboboxInput } from './useComboboxInput'

type PaletteKeyCommand = 'next' | 'previous' | 'choose' | 'close'

function paletteKeyCommand(event: KeyboardEvent<HTMLElement>): PaletteKeyCommand | null {
    switch (event.key) {
        case 'ArrowDown':
            return 'next'
        case 'ArrowUp':
            return 'previous'
        case 'Enter':
            return event.nativeEvent.isComposing ? null : 'choose'
        case 'Escape':
            return 'close'
        default:
            return null
    }
}

/** A click on the trigger is left to the trigger, which toggles the palette. */
function useCloseOnPointerOutside(
    rootRef: RefObject<HTMLElement>,
    trigger: RefObject<HTMLElement> | undefined,
    onClose: () => void
): void {
    useEffect(() => {
        const onPointerDown = (event: PointerEvent): void => {
            const target = event.target as Node
            if (!rootRef.current?.contains(target) && !trigger?.current?.contains(target)) {
                onClose()
            }
        }
        document.addEventListener('pointerdown', onPointerDown, true)
        return () => document.removeEventListener('pointerdown', onPointerDown, true)
    }, [rootRef, onClose, trigger])
}

const startsSection = (items: PaletteItem<CanvasCommand>[], index: number): boolean =>
    index === 0 || items[index - 1].section !== items[index].section

export function StepPalette({
    sections,
    commands = [],
    initialQuery = '',
    placeholder,
    trigger,
    onSelectStep,
    onClose,
}: {
    sections: PaletteSection[]
    commands?: CanvasCommand[]
    initialQuery?: string
    placeholder: string
    trigger?: RefObject<HTMLElement>
    onSelectStep: (step: CreateActionType) => void
    onClose: () => void
}): JSX.Element {
    const [query, setQuery] = useState(initialQuery)
    const [activeIndex, setActiveIndex] = useState(0)
    const rootRef = useRef<HTMLDivElement>(null)
    const listRef = useRef<HTMLDivElement>(null)
    const inputRef = useRef<HTMLInputElement>(null)
    const listId = useId()
    const optionId = (index: number): string => `${listId}-option-${index}`
    const items = useMemo(() => filterPaletteItems(query, sections, commands), [query, sections, commands])
    useComboboxInput(inputRef, listId, items.length ? optionId(activeIndex) : undefined)
    useCloseOnPointerOutside(rootRef, trigger, onClose)

    useEffect(() => setActiveIndex(0), [query])
    useEffect(() => {
        listRef.current?.querySelector(`[data-index="${activeIndex}"]`)?.scrollIntoView({ block: 'nearest' })
    }, [activeIndex])

    const choose = (item: PaletteItem<CanvasCommand> | undefined): void => {
        if (!item) {
            return
        }
        onClose()
        if (item.kind === 'step') {
            onSelectStep(item.step)
        } else {
            item.command.run()
        }
    }

    const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
        const command = paletteKeyCommand(event)
        if (command === 'close') {
            event.stopPropagation()
            onClose()
            trigger?.current?.focus()
            return
        }
        if (!command) {
            return
        }
        event.preventDefault()
        if (command === 'next') {
            setActiveIndex(Math.min(activeIndex + 1, items.length - 1))
        } else if (command === 'previous') {
            setActiveIndex(Math.max(activeIndex - 1, 0))
        } else {
            choose(items[activeIndex])
        }
    }

    return (
        <div
            ref={rootRef}
            className="flex w-95 max-w-[calc(100cqw-2rem)] flex-col overflow-hidden rounded-lg border bg-surface-primary shadow-xl"
            data-attr="workflow-step-palette"
            onKeyDown={onKeyDown}
        >
            <div className="border-b p-2">
                <LemonInput
                    autoFocus
                    fullWidth
                    inputRef={inputRef}
                    placeholder={placeholder}
                    value={query}
                    onChange={setQuery}
                />
            </div>
            <div
                ref={listRef}
                id={listId}
                role="listbox"
                aria-label={placeholder}
                className="max-h-90 overflow-y-auto p-1"
            >
                {items.length === 0 && <div className="p-3 text-sm text-secondary">Nothing matches your search.</div>}
                {items.map((item, index) => (
                    <div key={item.key}>
                        {startsSection(items, index) && (
                            <div className="px-2 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wider text-secondary">
                                {item.section}
                            </div>
                        )}
                        <StepPaletteRow
                            item={item}
                            id={optionId(index)}
                            index={index}
                            active={index === activeIndex}
                            onHover={() => setActiveIndex(index)}
                            onChoose={() => choose(item)}
                        />
                    </div>
                ))}
            </div>
            <div className="flex gap-3 border-t px-3 py-1.5 text-[11px] text-secondary">
                <span>↑↓ to move</span>
                <span>Enter to choose</span>
                <span>Esc to close</span>
            </div>
        </div>
    )
}
