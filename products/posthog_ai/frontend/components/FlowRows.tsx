import { useActions, useValues } from 'kea'
import { type ReactNode, memo, useCallback, useId, useLayoutEffect, useMemo, useRef } from 'react'

import { flowRowsLogic } from '../logics/flowRowsLogic'
import { deriveFlowWindow, renderedFlowRanges } from '../utils/flowWindow'
import { FlowScrollKeeper } from './FlowScrollKeeper'
import { VirtualizedThreadRowContext, type VirtualizedThreadRowContextValue } from './VirtualizedThreadRowContext'

const FlowRow = memo(function FlowRow({ index, children }: { index: number; children: ReactNode }): JSX.Element {
    const value = useMemo<VirtualizedThreadRowContextValue>(() => ({ index }), [index])
    return <VirtualizedThreadRowContext.Provider value={value}>{children}</VirtualizedThreadRowContext.Provider>
})

const FlowItemRow = memo(function FlowItemRow<T>({
    index,
    item,
    render,
}: {
    index: number
    item: T
    render: (item: T, index: number) => ReactNode
}): JSX.Element {
    return <FlowRow index={index}>{render(item, index)}</FlowRow>
}) as <T>(props: { index: number; item: T; render: (item: T, index: number) => ReactNode }) => JSX.Element

export interface FlowRowsProps<T> {
    items: T[]
    getItemKey: (item: T, index: number) => string
    header: ReactNode
    footer: ReactNode
    footerIndex: number
    render: (item: T, index: number) => ReactNode
}

/**
 * The rows of a flow-mode thread, in document flow. The newest rows render at once and the older
 * rows fill in between frames (see `flowRowsLogic`), so opening a long thread never freezes the page.
 */
export function FlowRows<T>({ items, getItemKey, header, footer, footerIndex, render }: FlowRowsProps<T>): JSX.Element {
    const keeperRef = useRef<FlowScrollKeeper>(null)
    const readerScrollTop = useCallback((): number | null => keeperRef.current?.readerScrollTop() ?? null, [])
    const logic = flowRowsLogic({ flowKey: useId(), readerScrollTop })
    const { flowWindow } = useValues(logic)
    const { syncWindow, chunkCommitted } = useActions(logic)
    // Derived during render, so a long append never renders in full for one frame before the window catches up.
    const current = deriveFlowWindow(flowWindow, items, getItemKey)

    useLayoutEffect(() => {
        if (current !== flowWindow) {
            syncWindow(current)
        }
    }, [current, flowWindow, syncWindow])

    useLayoutEffect(() => {
        chunkCommitted(performance.now())
    }, [current.fillStep, chunkCommitted])

    const rows: JSX.Element[] = []
    for (const [from, to] of renderedFlowRanges(current)) {
        for (let index = from; index < to; index++) {
            const item = items[index]
            rows.push(<FlowItemRow key={getItemKey(item, index)} index={index} item={item} render={render} />)
        }
    }

    return (
        <>
            <FlowScrollKeeper
                ref={keeperRef}
                fillStep={current.fillStep}
                holdTop={current.fillAtStart}
                filling={current.holes.length > 0}
            />
            {header != null && current.holes[0]?.[0] !== 0 && (
                <FlowRow key="header" index={0}>
                    {header}
                </FlowRow>
            )}
            {rows}
            {footer != null && (
                <FlowRow key="footer" index={footerIndex}>
                    {footer}
                </FlowRow>
            )}
        </>
    )
}
