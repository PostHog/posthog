import {
    JSX,
    KeyboardEvent as ReactKeyboardEvent,
    RefObject,
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import type { ConversationItem } from './buildConversationItems'
import {
    applyHighlights,
    clearHighlights,
    findMatchesInItems,
    HIGHLIGHT_ACTIVE,
    HIGHLIGHT_MATCH,
    highlightsSupported,
    type SearchMatch,
} from './conversationSearch'
import { ICONS, IconX } from './primitives/icons'
import type { VirtualizedListHandle } from './VirtualizedList'

const IconPrev = ICONS.ArrowUp
const IconNext = ICONS.ArrowDown

// ::highlight() pseudo-elements can't be expressed with Tailwind utilities, so
// the rules ship inline with the component. Only highlight-paintable properties
// (color, background-color, text-decoration, ...) are valid here.
const HIGHLIGHT_STYLES = `
::highlight(${HIGHLIGHT_MATCH}) { background-color: rgba(217, 170, 76, 0.3); }
::highlight(${HIGHLIGHT_ACTIVE}) { background-color: rgba(217, 170, 76, 0.7); }
`

export interface ConversationSearchBarProps {
    items: ConversationItem[]
    /** Element containing the virtualized scroll container (`[data-attr="virtualized-list-scroll"]`). */
    rootRef: RefObject<HTMLElement | null>
    /** Handle of the VirtualizedList rendering the items — navigation scrolls via `scrollToIndex`. */
    listRef: RefObject<VirtualizedListHandle | null>
    /** Render the bar open on mount instead of waiting for Cmd/Ctrl+F. */
    defaultOpen?: boolean
    onClose?: () => void
}

/**
 * In-conversation search. Self-managing: listens for Cmd/Ctrl+F to open,
 * computes matches from the conversation items, highlights them in the DOM via
 * the CSS Custom Highlight API and scrolls the active match into view.
 * Renders nothing while closed. Requires every conversation item wrapper to
 * carry a `data-conversation-item-id` attribute.
 */
export function ConversationSearchBar({
    items,
    rootRef,
    listRef,
    defaultOpen = false,
    onClose,
}: ConversationSearchBarProps): JSX.Element | null {
    const [open, setOpen] = useState(defaultOpen)
    const [query, setQuery] = useState('')
    const [currentIndex, setCurrentIndex] = useState(0)
    const inputRef = useRef<HTMLInputElement>(null)
    const lastScrolledQueryRef = useRef('')

    const matches = useMemo<SearchMatch[]>(() => findMatchesInItems(items, query), [items, query])
    const totalMatches = matches.length
    // Streaming items can shrink the match list under the cursor.
    const clampedIndex = totalMatches > 0 ? Math.min(currentIndex, totalMatches - 1) : 0

    // Items may be virtualized out of the DOM, so navigation goes through the
    // VirtualizedList handle (centers the item, unpins any follow-to-bottom);
    // the MutationObserver below re-applies highlights once the row mounts.
    const scrollToMatch = useCallback(
        (match: SearchMatch): void => {
            listRef.current?.scrollToIndex(match.itemIndex)
        },
        [listRef]
    )

    const getScrollContainer = useCallback(
        (): HTMLElement | null =>
            rootRef.current?.querySelector<HTMLElement>('[data-attr="virtualized-list-scroll"]') ?? null,
        [rootRef]
    )

    const handleQueryChange = useCallback((value: string): void => {
        setQuery(value)
        setCurrentIndex(0)
    }, [])

    const goTo = useCallback(
        (index: number): void => {
            if (totalMatches === 0) {
                return
            }
            const wrapped = ((index % totalMatches) + totalMatches) % totalMatches
            setCurrentIndex(wrapped)
            scrollToMatch(matches[wrapped])
        },
        [matches, totalMatches, scrollToMatch]
    )

    const next = useCallback((): void => goTo(clampedIndex + 1), [goTo, clampedIndex])
    const prev = useCallback((): void => goTo(clampedIndex - 1), [goTo, clampedIndex])

    const close = useCallback((): void => {
        setOpen(false)
        setQuery('')
        setCurrentIndex(0)
        lastScrolledQueryRef.current = ''
        clearHighlights()
        onClose?.()
    }, [onClose])

    // Global Cmd/Ctrl+F: open the bar, or refocus + select-all when already open.
    useEffect(() => {
        const onKeyDown = (e: KeyboardEvent): void => {
            if (!(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey || e.key.toLowerCase() !== 'f') {
                return
            }
            e.preventDefault()
            setOpen(true)
            const input = inputRef.current
            if (input) {
                input.focus()
                input.select()
            }
        }
        window.addEventListener('keydown', onKeyDown, { capture: true })
        return () => window.removeEventListener('keydown', onKeyDown, { capture: true })
    }, [])

    useEffect(() => {
        if (open) {
            inputRef.current?.focus()
        }
    }, [open])

    // Jump to the first match when a new query produces results.
    useEffect(() => {
        if (!query || matches.length === 0 || lastScrolledQueryRef.current === query) {
            return
        }
        lastScrolledQueryRef.current = query
        scrollToMatch(matches[0])
    }, [query, matches, scrollToMatch])

    // Apply CSS custom highlights. The latest apply function lives in a ref so
    // the long-lived MutationObserver below can re-run it without being torn
    // down and recreated on every match or active-index change.
    const applyHighlightsRef = useRef<() => void>(() => {})

    useEffect(() => {
        if (!open || !highlightsSupported()) {
            applyHighlightsRef.current = () => {}
            return
        }
        const container = getScrollContainer()
        if (!container || !query || matches.length === 0) {
            applyHighlightsRef.current = () => {}
            clearHighlights()
            return
        }
        const active = matches[clampedIndex] ?? null
        applyHighlightsRef.current = () => {
            applyHighlights(container, query, matches, active)
        }
        applyHighlightsRef.current()
    }, [open, query, matches, clampedIndex, getScrollContainer])

    // Reapply highlights whenever the conversation DOM mutates (streaming
    // updates re-render items under the highlighted ranges). Created once per
    // open, independent of match selection.
    useEffect(() => {
        if (!open || !highlightsSupported()) {
            return
        }
        const container = getScrollContainer()
        if (!container) {
            return
        }
        const observer = new MutationObserver(() => applyHighlightsRef.current())
        observer.observe(container, { childList: true, subtree: true, characterData: true })
        return () => observer.disconnect()
    }, [open, getScrollContainer])

    useEffect(() => () => clearHighlights(), [])

    const handleInputKeyDown = useCallback(
        (e: ReactKeyboardEvent<HTMLInputElement>): void => {
            if (e.key === 'Escape') {
                e.preventDefault()
                e.stopPropagation()
                close()
            } else if (e.key === 'Enter' || e.key === 'ArrowDown') {
                e.preventDefault()
                if (e.shiftKey) {
                    prev()
                } else {
                    next()
                }
            } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                prev()
            }
        },
        [close, next, prev]
    )

    if (!open) {
        return null
    }

    return (
        <div className="absolute top-2 right-6 z-30 flex items-center gap-1 rounded border border-border bg-bg-light px-1.5 py-1 shadow-md">
            <style>{HIGHLIGHT_STYLES}</style>
            <LemonInput
                type="search"
                size="small"
                value={query}
                onChange={handleQueryChange}
                onKeyDown={handleInputKeyDown}
                inputRef={inputRef}
                placeholder="Find in conversation..."
                autoFocus
                transparentBackground
                className="w-56 border-none"
                aria-label="Find in conversation"
            />
            {query && (
                <span className="shrink-0 whitespace-nowrap text-xs text-muted">
                    {totalMatches > 0 ? `${clampedIndex + 1} of ${totalMatches}` : 'No results'}
                </span>
            )}
            <LemonButton
                size="xsmall"
                icon={<IconPrev />}
                onClick={prev}
                disabledReason={totalMatches === 0 ? 'No matches' : undefined}
                tooltip="Previous match"
                aria-label="Previous match"
            />
            <LemonButton
                size="xsmall"
                icon={<IconNext />}
                onClick={next}
                disabledReason={totalMatches === 0 ? 'No matches' : undefined}
                tooltip="Next match"
                aria-label="Next match"
            />
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                onClick={close}
                tooltip="Close search"
                aria-label="Close search"
            />
        </div>
    )
}
