import { type ReactElement, useEffect, useMemo, useRef, useState } from 'react'

import { LemonMenu, type LemonMenuItem, type LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { type SlashCommand, filterSlashCommands } from '../../utils/slashCommands'
import { useComposerContext } from './Composer'

// `matchWidth` sets only a min-width, so a row has to carry the cap that bounds the menu.
// The scroll margin clears the enclosing button's padding for `scrollIntoView`.
const ROW_CLASSES = 'w-full max-w-xl min-w-0 scroll-my-2'

// About five rows. Capping the list rather than the popover leaves the section footer in view; the
// selector matches LemonMenu's section markup, where the rows are the `<ul>` next to that footer.
const MENU_LIST_CLASSES = '[&_section>ul]:max-h-52 [&_section>ul]:overflow-y-auto'

export interface ComposerCommandMenuProps {
    commands: SlashCommand[]
    /** The element the menu anchors to, usually `Composer.Field`. It must forward a ref. */
    children: ReactElement
}

/** Keeps the highlighted command in view: the list caps its height, so a long list scrolls. */
function CommandMenuItemLabel({ command, active }: { command: SlashCommand; active: boolean }): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)
    useEffect(() => {
        if (active) {
            ref.current?.scrollIntoView({ block: 'nearest' })
        }
    }, [active])
    return (
        <div className={ROW_CLASSES} ref={ref}>
            <div className="font-mono truncate">
                /{command.name}
                {command.hint && <span className="text-muted"> {command.hint}</span>}
            </div>
            {command.description && <div className="text-muted text-xs truncate">{command.description}</div>}
        </div>
    )
}

/**
 * Suggests slash commands while the draft is a lone `/name` token. Selecting a command writes `/name ` into
 * the draft, so the user can add arguments and then send it. Logic-free: the caller passes the commands.
 */
export function ComposerCommandMenu({ commands, children }: ComposerCommandMenuProps): JSX.Element {
    const { value, onChange, textAreaRef } = useComposerContext()
    const filtered = useMemo(() => filterSlashCommands(commands, value), [commands, value])
    const [activeIndex, setActiveIndex] = useState(0)
    // Escape hides the menu for the draft it was pressed on. Typing re-opens it.
    const [dismissedFor, setDismissedFor] = useState<string | null>(null)
    const visible = filtered.length > 0 && dismissedFor !== value
    // Only the app's own commands exist until the agent advertises its list over the stream.
    const hasAgentCommands = commands.some((command) => command.source === 'agent')

    useEffect(() => {
        setActiveIndex(0)
    }, [filtered])

    // Dismissal is keyed on the draft it was pressed on, so a later edit re-opens the menu. Drop it once
    // the draft moves on, otherwise deleting the draft and typing the same text again stays dismissed.
    useEffect(() => {
        setDismissedFor((dismissed) => (dismissed === null || dismissed === value ? dismissed : null))
    }, [value])

    const select = (command: SlashCommand | undefined): void => {
        if (!command) {
            return
        }
        onChange(`/${command.name} `)
        textAreaRef.current?.focus()
    }

    useEffect(() => {
        if (!visible) {
            return
        }
        const handleKeyDown = (e: KeyboardEvent): void => {
            if (e.target !== textAreaRef.current) {
                return
            }
            if (e.key === 'ArrowDown') {
                e.preventDefault()
                setActiveIndex((index) => (index + 1) % filtered.length)
            } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                setActiveIndex((index) => (index - 1 + filtered.length) % filtered.length)
            } else if ((e.key === 'Enter' && !e.shiftKey) || (e.key === 'Tab' && !e.shiftKey)) {
                e.preventDefault()
                e.stopPropagation()
                select(filtered[activeIndex])
            } else if (e.key === 'Escape') {
                e.preventDefault()
                e.stopPropagation()
                setDismissedFor(value)
            }
        }
        // Capture phase, so Enter selects a command before the textarea submits the draft.
        document.addEventListener('keydown', handleKeyDown, { capture: true })
        return () => document.removeEventListener('keydown', handleKeyDown, { capture: true })
    })

    const items: LemonMenuItems = [
        {
            key: 'commands',
            items: filtered.map(
                (command, index): LemonMenuItem => ({
                    key: command.name,
                    label: <CommandMenuItemLabel command={command} active={index === activeIndex} />,
                    onClick: () => select(command),
                    active: index === activeIndex,
                    'data-attr': `sandbox-composer-slash-command-${command.source}`,
                })
            ),
            footer: (
                <div className="border-t px-1 pt-1.5 pb-0.5 mt-1 text-xxs text-muted-alt font-medium select-none">
                    {!hasAgentCommands && <div className="mb-0.5">The agent adds its own commands once it starts</div>}
                    ↑↓ to navigate • ⏎ or Tab to select • Esc to close
                </div>
            ),
        },
    ]

    return (
        <LemonMenu
            matchWidth
            className={MENU_LIST_CLASSES}
            items={items}
            visible={visible}
            closeOnClickInside={false}
            // The textarea sits outside the floating menu, so a click that moves the caret counts as outside.
            onClickOutside={(event) => {
                if (event.target !== textAreaRef.current) {
                    setDismissedFor(value)
                }
            }}
            placement="top-start"
            fallbackPlacements={['bottom-start']}
            focusBasedKeyboardNavigation={false}
        >
            {children}
        </LemonMenu>
    )
}
