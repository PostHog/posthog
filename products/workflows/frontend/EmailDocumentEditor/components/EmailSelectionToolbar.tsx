import type { Editor } from '@tiptap/core'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, Popover } from '@posthog/lemon-ui'

import { IconLink } from 'lib/lemon-ui/icons'

import { safeEmailLink } from '../renderEmailHtml'
import { EmailFormatButton, EmailFormatButtons } from './EmailFormatButtons'
import { useEscapeToClose } from './useEscapeToClose'

const FULL_LINK_HINT = 'Enter a full link, such as https://example.com'

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
    useEscapeToClose(linkOpen, () => {
        setLinkOpen(false)
        editor.commands.focus()
    })
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

    const value = href.trim()
    const safeLink = safeEmailLink(value)
    const invalidLink = !!value && !safeLink
    const applyLink = (): void => {
        if (!value) {
            editor.chain().focus().extendMarkRange('link').unsetLink().run()
        } else {
            if (invalidLink) {
                return
            }
            editor.chain().focus().extendMarkRange('link').setLink({ href: safeLink }).run()
        }
        setLinkOpen(false)
    }

    return (
        <div
            className="absolute z-20 flex gap-0.5 p-0.5 border rounded bg-surface-primary shadow-sm"
            style={{ top: Math.max(0, top), left }}
            role="toolbar"
            aria-label="Format text"
            data-attr="email-editor-selection-toolbar"
        >
            <EmailFormatButtons editor={editor} attrPrefix="email-editor-format" />
            <Popover
                visible={linkOpen}
                onClickOutside={() => setLinkOpen(false)}
                placement="bottom-start"
                overlay={
                    <div
                        className="flex flex-col gap-1 p-2 w-80"
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                                event.preventDefault()
                                applyLink()
                            }
                        }}
                    >
                        <div className="flex gap-1">
                            <LemonInput
                                size="small"
                                className="flex-1"
                                autoFocus
                                placeholder="https://example.com"
                                value={href}
                                onChange={setHref}
                                status={invalidLink ? 'danger' : 'default'}
                                data-attr="email-editor-link-input"
                            />
                            <LemonButton
                                size="small"
                                type="primary"
                                onClick={applyLink}
                                data-attr="email-editor-link-apply"
                                disabledReason={
                                    invalidLink
                                        ? FULL_LINK_HINT
                                        : !value && !editor.isActive('link')
                                          ? 'Enter a link'
                                          : undefined
                                }
                            >
                                {value || !editor.isActive('link') ? 'Apply' : 'Remove'}
                            </LemonButton>
                        </div>
                        {invalidLink ? <span className="text-xs text-danger">{FULL_LINK_HINT}</span> : null}
                    </div>
                }
            >
                <EmailFormatButton
                    active={editor.isActive('link')}
                    label="Link"
                    attr="email-editor-format-link"
                    onClick={() => {
                        setHref(editor.getAttributes('link').href ?? '')
                        setLinkOpen(!linkOpen)
                    }}
                >
                    <IconLink />
                </EmailFormatButton>
            </Popover>
        </div>
    )
}
