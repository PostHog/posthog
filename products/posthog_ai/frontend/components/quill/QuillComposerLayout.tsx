import { type ReactNode, type RefObject, useLayoutEffect, useRef, useState } from 'react'

import { InputGroup, InputGroupAddon } from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'

export interface QuillComposerLayoutProps {
    groupRef: RefObject<HTMLDivElement>
    textAreaRef: RefObject<HTMLTextAreaElement>
    chips?: ReactNode
    field: ReactNode
    send: ReactNode
    controls?: ReactNode
    meta?: ReactNode
    singleRow?: boolean
}

const SINGLE_ROW_CLASS =
    'pr-1.5 pb-1.5 ' +
    '[&_.quill-button--size-sm]:h-7 [&_.quill-button--size-lg]:h-7 [&_.quill-button--size-lg]:px-2 [&_.quill-button--size-lg]:text-xs ' +
    '[&_.quill-button--size-icon-sm]:size-7 [&_.quill-button--size-icon-sm_svg]:size-3.5 [&_[data-attr=task-composer-add-menu]]:-ml-[3px]'

function useTwoRows(
    rowRef: RefObject<HTMLDivElement>,
    controlsRef: RefObject<HTMLDivElement>,
    metaRef: RefObject<HTMLDivElement>,
    sendRef: RefObject<HTMLDivElement>,
    enabled: boolean
): boolean {
    const [twoRows, setTwoRows] = useState(false)

    useLayoutEffect(() => {
        const row = rowRef.current
        const parts = [controlsRef.current, metaRef.current, sendRef.current]
        if (!enabled || !row || parts.some((part) => !part) || typeof ResizeObserver === 'undefined') {
            return
        }
        const [controls, metaGroup, sendGroup] = parts as HTMLDivElement[]
        const measure = (): void => {
            const style = getComputedStyle(row)
            const available = row.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
            const gap = parseFloat(style.columnGap) || 0
            const metaWidth = Array.from(metaGroup.children).reduce((sum, child) => sum + child.scrollWidth, 0)
            const needed = controls.scrollWidth + metaWidth + sendGroup.scrollWidth + gap * 2
            setTwoRows(needed > available + 0.5)
        }
        measure()
        const resizeObserver = new ResizeObserver(measure)
        resizeObserver.observe(row)
        resizeObserver.observe(controls)
        Array.from(metaGroup.children).forEach((child) => resizeObserver.observe(child))
        const mutationObserver = new MutationObserver(measure)
        mutationObserver.observe(row, { childList: true, subtree: true, characterData: true })
        return () => {
            resizeObserver.disconnect()
            mutationObserver.disconnect()
        }
    }, [rowRef, controlsRef, metaRef, sendRef, enabled])

    return enabled && twoRows
}

export function QuillComposerLayout({
    groupRef,
    textAreaRef,
    chips,
    field,
    send,
    controls,
    meta,
    singleRow = false,
}: QuillComposerLayoutProps): JSX.Element {
    const chipsRowRef = useRef<HTMLDivElement>(null)
    const chipsContentRef = useRef<HTMLDivElement>(null)
    const rowRef = useRef<HTMLDivElement>(null)
    const controlsRef = useRef<HTMLDivElement>(null)
    const metaRef = useRef<HTMLDivElement>(null)
    const sendRef = useRef<HTMLDivElement>(null)
    const twoRows = useTwoRows(rowRef, controlsRef, metaRef, sendRef, singleRow)

    useLayoutEffect(() => {
        const row = chipsRowRef.current
        const content = chipsContentRef.current
        if (!row || !content || typeof ResizeObserver === 'undefined') {
            return
        }
        const sync = (): void => {
            const hasChips = Array.from(content.children).some((child) => (child as HTMLElement).offsetHeight > 0)
            row.style.setProperty('height', hasChips ? `${content.offsetHeight}px` : '0px', 'important')
        }
        row.style.setProperty('padding-block', '0px', 'important')
        sync()
        row.dataset.ready = 'true'
        const observer = new ResizeObserver(sync)
        observer.observe(content)
        return () => observer.disconnect()
    }, [])

    return (
        <div className="flex flex-col gap-1">
            <InputGroup
                ref={groupRef}
                onClick={(event) => {
                    if (!(event.target as HTMLElement).closest('button, a, input, textarea, [role="menu"]')) {
                        textAreaRef.current?.focus()
                    }
                }}
                className={
                    // The textarea is Lemon's, so quill's own focus rule, keyed to its input slot, never fires here.
                    'h-auto cursor-text flex-col bg-[var(--card)] focus-within:border-[color-mix(in_oklab,var(--ring)_50%,transparent)] focus-within:shadow-[0_0_0_3px_color-mix(in_oklab,var(--ring)_30%,transparent)] ' +
                    // LemonTextArea puts the composer's padding on both its wrapper and the textarea. The wrapper keeps it, so the textarea drops it. The textarea keeps 2px on the left because it clips the caret at x=0.
                    '[&_[data-slot=composer-placeholder]]:top-2 [&_[data-slot=composer-placeholder]]:left-2.5 [&_[data-slot=composer-placeholder]]:right-0 [&_[data-slot=composer-placeholder]]:truncate [&_textarea]:p-0 [&_textarea]:pl-0.5 ' +
                    // One line tall at rest: the field is only as tall as the send button and its ledge need, then grows with the text.
                    '[&_:has(>textarea)]:min-h-10 [&_:has(>textarea)]:pr-1 [&_textarea]:min-h-0'
                }
            >
                {chips && (
                    <InputGroupAddon
                        ref={chipsRowRef}
                        align="block-start"
                        className="min-h-0 overflow-hidden data-[ready=true]:transition-[height] data-[ready=true]:duration-200 data-[ready=true]:ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none!"
                    >
                        <div
                            ref={chipsContentRef}
                            className="flex w-full flex-wrap items-center gap-2 pt-2.5 pb-1.5 [&_.LemonTag]:h-6 [&_.LemonTag]:gap-1 [&_.LemonTag]:rounded-sm [&_.LemonTag]:px-2 [&_.LemonTag]:text-xs *:transition-[opacity,translate] *:duration-[180ms] *:ease-[cubic-bezier(0.19,1,0.22,1)] *:starting:-translate-y-1 *:starting:opacity-0 motion-reduce:*:transition-[opacity] motion-reduce:*:starting:translate-y-0"
                        >
                            {chips}
                        </div>
                    </InputGroupAddon>
                )}
                <div className="relative w-full min-w-0">{field}</div>
                {singleRow ? (
                    <div
                        ref={rowRef}
                        data-quill
                        data-two-rows={twoRows || undefined}
                        className={cn(
                            '@container/composer w-full items-center gap-1 pl-1.5 text-[var(--muted-foreground)]',
                            SINGLE_ROW_CLASS,
                            twoRows ? 'grid grid-cols-[auto_1fr_auto]' : 'flex flex-nowrap'
                        )}
                    >
                        <div ref={controlsRef} className="col-start-1 row-start-1 flex shrink-0 items-center gap-1">
                            {controls}
                        </div>
                        <div
                            ref={metaRef}
                            className={cn(
                                'flex min-w-0 items-center',
                                twoRows ? 'col-span-full row-start-2 -ml-1' : 'ml-auto'
                            )}
                        >
                            {meta}
                        </div>
                        <div ref={sendRef} className="col-start-3 row-start-1 flex shrink-0 items-center">
                            {send}
                        </div>
                    </div>
                ) : (
                    <div
                        data-quill
                        className="@container/composer flex w-full flex-wrap items-center gap-1 pr-1 pb-1 pl-1.5 text-[var(--muted-foreground)]"
                    >
                        {controls}
                        <div className="ml-auto flex shrink-0 items-center gap-1">
                            {meta}
                            {send}
                        </div>
                    </div>
                )}
            </InputGroup>
        </div>
    )
}
