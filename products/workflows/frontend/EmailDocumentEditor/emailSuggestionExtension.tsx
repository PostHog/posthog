import { Extension, Editor, Range } from '@tiptap/core'
import { PluginKey } from '@tiptap/pm/state'
import { ReactRenderer } from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import { forwardRef, useEffect, useImperativeHandle, useState } from 'react'

import { LemonButton, Popover } from '@posthog/lemon-ui'

export interface EmailSuggestionItem {
    key: string
    title: string
    detail?: string
    icon?: JSX.Element
    run: (editor: Editor, range: Range) => void
}

interface MenuProps {
    items: EmailSuggestionItem[]
    command: (item: EmailSuggestionItem) => void
    decorationNode?: Element | null
    empty: string
}

interface MenuRef {
    onKeyDown: (event: KeyboardEvent) => boolean
}

const EmailSuggestionList = forwardRef<MenuRef, MenuProps>(function EmailSuggestionList(
    { items, command, decorationNode, empty },
    ref
): JSX.Element {
    const [index, setIndex] = useState(0)

    useEffect(() => setIndex(0), [items])

    useImperativeHandle(ref, () => ({
        onKeyDown: (event) => {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                const step = event.key === 'ArrowDown' ? 1 : -1
                setIndex((current) => (current + step + items.length) % Math.max(items.length, 1))
                return true
            }
            if (event.key === 'Enter' || event.key === 'Tab') {
                if (items[index]) {
                    command(items[index])
                    return true
                }
                return false
            }
            return false
        },
    }))

    // Once nothing matches, what's being typed is just text, so the menu shouldn't sit over it.
    return (
        <Popover
            visible={items.length > 0 || !!empty}
            placement="bottom-start"
            fallbackPlacements={['top-start']}
            referenceElement={decorationNode as HTMLElement}
            overlay={
                <div className="flex flex-col max-h-72 overflow-y-auto w-72 p-1" data-attr="email-editor-suggestions">
                    {items.length ? (
                        items.map((item, itemIndex) => (
                            <LemonButton
                                key={item.key}
                                size="small"
                                fullWidth
                                icon={item.icon}
                                active={itemIndex === index}
                                onMouseDown={(event) => event.preventDefault()}
                                onClick={() => command(item)}
                                sideIcon={null}
                            >
                                <span className="flex flex-col items-start min-w-0">
                                    <span className="truncate max-w-60">{item.title}</span>
                                    {item.detail ? (
                                        <span className="text-xs text-secondary font-normal truncate max-w-60">
                                            {item.detail}
                                        </span>
                                    ) : null}
                                </span>
                            </LemonButton>
                        ))
                    ) : (
                        <span className="p-2 text-secondary text-xs">{empty}</span>
                    )}
                </div>
            }
        >
            <span />
        </Popover>
    )
})

export function createEmailSuggestion(options: {
    name: string
    char: string
    empty: string
    items: (query: string, editor: Editor) => EmailSuggestionItem[]
}): Extension {
    return Extension.create({
        name: options.name,
        addProseMirrorPlugins() {
            return [
                Suggestion<EmailSuggestionItem>({
                    pluginKey: new PluginKey(options.name),
                    editor: this.editor,
                    char: options.char,
                    allowSpaces: true,
                    // A slash only opens the menu at the start of a word, so `and/or` stays plain text.
                    allowedPrefixes: options.char === '/' ? [' '] : null,
                    items: ({ query, editor }) => options.items(query, editor),
                    command: ({ editor, range, props }) => props.run(editor, range),
                    render: () => {
                        let renderer: ReactRenderer<MenuRef, MenuProps> | null = null
                        const destroy = (): void => {
                            renderer?.destroy()
                            renderer = null
                        }
                        return {
                            onStart: (props) => {
                                renderer = new ReactRenderer(EmailSuggestionList, {
                                    editor: props.editor,
                                    props: { ...props, empty: options.empty },
                                })
                            },
                            onUpdate: (props) => renderer?.updateProps({ ...props, empty: options.empty }),
                            onKeyDown: ({ event }) => {
                                if (event.key === 'Escape') {
                                    destroy()
                                    return true
                                }
                                return renderer?.ref?.onKeyDown(event) ?? false
                            },
                            onExit: destroy,
                        }
                    },
                }),
            ]
        },
    })
}
