import './Suggestions.scss'

import { createContext, type ReactNode, useContext, useEffect, useRef } from 'react'

import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { useAnimatedPresence } from 'lib/hooks/useAnimatedPresence'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'
import { cn } from 'lib/utils/css-classes'

// Radix-style compound suggestions surface: a logic-free button row ("Try PostHog AI for…") plus an
// in-input dropdown that opens when a multi-suggestion category is picked. Reproduces the look of
// scenes/max's FloatingSuggestionsDisplay + SuggestionsList without any conversation logic — the caller owns
// the open state and decides what a chosen suggestion does (fill, submit, navigate). The dropdown attaches
// to the bottom edge of whatever positioned ancestor it's placed in (e.g. inside <Composer.Root>).

export interface SuggestionItem {
    content: string
    /** When true the caller should fill the input and let the user finish typing; otherwise submit directly. */
    requiresUserInput?: boolean
}

export interface SuggestionGroup {
    label: string
    icon: JSX.Element
    suggestions: SuggestionItem[]
    /** Optional product page to open when the group is clicked (handled by the caller's `onNavigate`). */
    url?: string
    tooltip?: string
}

interface SuggestionsContextValue {
    activeGroup: SuggestionGroup | null
    handleGroupClick: (group: SuggestionGroup) => void
    handleSelect: (item: SuggestionItem) => void
    disabled: boolean
    disabledReason?: string | null
}

const SuggestionsContext = createContext<SuggestionsContextValue | null>(null)

function useSuggestionsContext(): SuggestionsContextValue {
    const ctx = useContext(SuggestionsContext)
    if (!ctx) {
        throw new Error('Suggestions.* components must be rendered inside <Suggestions.Root>')
    }
    return ctx
}

export interface SuggestionsRootProps {
    /** Controlled open-dropdown state; `null` when no category is expanded. The caller owns it. */
    activeGroup: SuggestionGroup | null
    onActiveGroupChange: (group: SuggestionGroup | null) => void
    /** Called when a concrete suggestion is chosen — from the dropdown or a single-suggestion group. */
    onSelectSuggestion: (item: SuggestionItem) => void
    /** Called (before the open/select logic) for groups carrying a `url`, e.g. to open the product page. */
    onNavigate?: (url: string) => void
    disabled?: boolean
    disabledReason?: string | null
    children: ReactNode
}

function SuggestionsRoot({
    activeGroup,
    onActiveGroupChange,
    onSelectSuggestion,
    onNavigate,
    disabled = false,
    disabledReason,
    children,
}: SuggestionsRootProps): JSX.Element {
    const handleGroupClick = (group: SuggestionGroup): void => {
        if (group.url) {
            onNavigate?.(group.url)
        }
        // ≤1 suggestion: nothing to expand, apply it straight away. Otherwise open the dropdown.
        if (group.suggestions.length <= 1) {
            if (group.suggestions[0]) {
                onSelectSuggestion(group.suggestions[0])
            }
        } else {
            onActiveGroupChange(group)
        }
    }

    const handleSelect = (item: SuggestionItem): void => {
        onSelectSuggestion(item)
        onActiveGroupChange(null)
    }

    // The dropdown dismisses on Esc or a click anywhere outside the suggestions subtree. The `contents`
    // wrapper is layout-transparent (it doesn't establish a box or positioning context, so the flex layout
    // and the dropdown's absolute positioning are unchanged) but gives `useOutsideClickHandler` one node that
    // spans every slot — so clicking another category button to switch groups doesn't count as "outside".
    const rootRef = useRef<HTMLDivElement | null>(null)
    useOutsideClickHandler([rootRef], () => {
        if (activeGroup) {
            onActiveGroupChange(null)
        }
    })

    useEffect(() => {
        if (!activeGroup) {
            return
        }
        const handleKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                onActiveGroupChange(null)
            }
        }
        document.addEventListener('keydown', handleKeyDown)
        return () => document.removeEventListener('keydown', handleKeyDown)
    }, [activeGroup, onActiveGroupChange])

    return (
        <SuggestionsContext.Provider value={{ activeGroup, handleGroupClick, handleSelect, disabled, disabledReason }}>
            <div ref={rootRef} className="contents">
                {children}
            </div>
        </SuggestionsContext.Provider>
    )
}

export interface SuggestionsButtonsProps {
    data: readonly SuggestionGroup[]
    /** The label above the row. Defaults to the PostHog AI prompt; pass `null` to hide it. */
    tip?: ReactNode
    type?: 'primary' | 'secondary' | 'tertiary'
    /** Extra buttons appended after the category buttons (e.g. a settings affordance). */
    additionalSuggestions?: ReactNode[]
    className?: string
}

function SuggestionsButtons({
    data,
    tip = 'Try PostHog AI for…',
    type = 'secondary',
    additionalSuggestions,
    className,
}: SuggestionsButtonsProps): JSX.Element {
    const { activeGroup, handleGroupClick, disabled, disabledReason } = useSuggestionsContext()

    return (
        <div className={cn('flex flex-col items-center justify-center gap-y-2', className)}>
            {tip && <h3 className="text-center text-xs font-medium mb-0 text-secondary">{tip}</h3>}
            <Tooltip title={disabled ? disabledReason || undefined : undefined}>
                <ul
                    className={cn(
                        'flex items-center justify-center flex-wrap gap-1.5 mb-0',
                        activeGroup && 'fade-out pointer-events-none'
                    )}
                >
                    {data.map((group) => (
                        <li key={group.label}>
                            <LemonButton
                                onClick={() => handleGroupClick(group)}
                                size="xsmall"
                                type={type}
                                icon={group.icon}
                                tooltip={disabled ? undefined : group.tooltip}
                                disabled={disabled}
                            >
                                {group.label}
                            </LemonButton>
                        </li>
                    ))}
                    {additionalSuggestions?.map((node, index) => (
                        <li key={index}>{node}</li>
                    ))}
                </ul>
            </Tooltip>
        </div>
    )
}

export interface SuggestionsDropdownProps {
    className?: string
}

function SuggestionsDropdown({ className }: SuggestionsDropdownProps): JSX.Element | null {
    const { activeGroup, handleSelect } = useSuggestionsContext()
    const containerRef = useRef<HTMLDivElement | null>(null)
    // Keep the last group around so its items stay rendered through the exit animation.
    const previousGroup = useRef<SuggestionGroup | null>(null)
    const { rendered, shown } = useAnimatedPresence(!!activeGroup, 150)

    useEffect(() => {
        if (activeGroup && containerRef.current) {
            // Move focus into the dropdown so keyboard users can act on it immediately.
            containerRef.current.querySelector<HTMLElement>('button')?.focus()
        }
        previousGroup.current = activeGroup
    }, [activeGroup, rendered])

    const group = activeGroup || previousGroup.current

    if (!rendered) {
        return null
    }

    return (
        <div
            ref={containerRef}
            role="listbox"
            className={cn(
                'Suggestions__list absolute inset-x-2 top-full grid auto-rows-auto p-1 border-x border-b rounded-b-lg bg-surface-primary z-10',
                shown && 'Suggestions__list--visible',
                className
            )}
        >
            {group?.suggestions.map((suggestion, index) => (
                <LemonButton
                    key={suggestion.content}
                    className="Suggestions__item text-left"
                    style={{ '--index': index } as React.CSSProperties}
                    size="small"
                    type="tertiary"
                    fullWidth
                    onClick={() => handleSelect(suggestion)}
                >
                    <span className="font-normal">{suggestion.content}</span>
                </LemonButton>
            ))}
        </div>
    )
}

export const Suggestions = Object.assign(SuggestionsRoot, {
    Root: SuggestionsRoot,
    Buttons: SuggestionsButtons,
    Dropdown: SuggestionsDropdown,
})
