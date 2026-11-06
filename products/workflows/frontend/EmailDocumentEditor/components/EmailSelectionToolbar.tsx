import type { Editor } from '@tiptap/core'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, Popover } from '@posthog/lemon-ui'

import { IconBold, IconItalic, IconLink } from 'lib/lemon-ui/icons'

import { safeEmailLink } from '../renderEmailHtml'

/** Formatting for selected text. It's positioned from the selection, because the canvas scrolls independently of the page. */
export function EmailSelectionToolbar({
    editor,
    container,
    openRequest,
}: {
    editor: Editor
    container: HTMLElement | null
    openRequest: number
}): JSX.Element | null {
    const { selection } = editor.state
    const [linkOpen, setLinkOpen] = useState(false)
    const [href, setHref] = useState('')
    const visible = !selection.empty && !('node' in selection) && editor.isEditable && (editor.isFocused || linkOpen)

    useEffect(() => {
        if (selection.empty) {
            setLinkOpen(false)
        }
    }, [selection.empty])

    useEffect(() => {
        if (openRequest) {
            setHref(editor.getAttributes('link').href ?? '')
            setLinkOpen(true)
        }
    }, [openRequest, editor])

    if (!visible || !container) {
        return null
    }

    const start = editor.view.coordsAtPos(selection.from)
    const parent = container.getBoundingClientRect()
    const top = start.top - parent.top + container.scrollTop - 38
    const left = Math.max(4, start.left - parent.left + container.scrollLeft)

    const applyLink = (): void => {
        const value = href.trim()
        if (!value) {
            editor.chain().focus().extendMarkRange('link').unsetLink().run()
        } else {
            const safe = safeEmailLink(value)
            if (!safe) {
                return
            }
            editor.chain().focus().extendMarkRange('link').setLink({ href: safe }).run()
        }
        setLinkOpen(false)
    }

    const mark = (name: string, label: string, content: JSX.Element, run: () => void): JSX.Element => (
        <LemonButton
            size="xsmall"
            active={editor.isActive(name)}
            aria-label={label}
            tooltip={label}
            onMouseDown={(event) => event.preventDefault()}
            onClick={run}
            data-attr={`email-editor-format-${name}`}
        >
            {content}
        </LemonButton>
    )

    return (
        <div
            className="absolute z-20 flex gap-0.5 p-0.5 border rounded bg-surface-primary shadow-sm"
            style={{ top: Math.max(0, top), left }}
            role="toolbar"
            aria-label="Format text"
            data-attr="email-editor-selection-toolbar"
        >
            {mark('bold', 'Bold', <IconBold />, () => editor.chain().focus().toggleBold().run())}
            {mark('italic', 'Italic', <IconItalic />, () => editor.chain().focus().toggleItalic().run())}
            {mark('underline', 'Underline', <span className="underline px-1 text-xs">U</span>, () =>
                editor.chain().focus().toggleUnderline().run()
            )}
            {mark('strike', 'Strikethrough', <span className="line-through px-1 text-xs">S</span>, () =>
                editor.chain().focus().toggleStrike().run()
            )}
            {mark('code', 'Code', <span className="font-mono px-0.5 text-xs">{'<>'}</span>, () =>
                editor.chain().focus().toggleCode().run()
            )}
            <Popover
                visible={linkOpen}
                onClickOutside={() => setLinkOpen(false)}
                placement="bottom-start"
                overlay={
                    <div
                        className="flex gap-1 p-2 w-80"
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                                event.preventDefault()
                                applyLink()
                            }
                            if (event.key === 'Escape') {
                                event.stopPropagation()
                                setLinkOpen(false)
                                editor.commands.focus()
                            }
                        }}
                    >
                        <LemonInput
                            size="small"
                            className="flex-1"
                            autoFocus
                            placeholder="https://example.com"
                            value={href}
                            onChange={setHref}
                            data-attr="email-editor-link-input"
                        />
                        <LemonButton
                            size="small"
                            type="primary"
                            onClick={applyLink}
                            data-attr="email-editor-link-apply"
                        >
                            {href.trim() ? 'Apply' : 'Remove'}
                        </LemonButton>
                    </div>
                }
            >
                <LemonButton
                    size="xsmall"
                    active={editor.isActive('link')}
                    aria-label="Link"
                    tooltip="Link"
                    icon={<IconLink />}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                        setHref(editor.getAttributes('link').href ?? '')
                        setLinkOpen(!linkOpen)
                    }}
                    data-attr="email-editor-format-link"
                />
            </Popover>
        </div>
    )
}
