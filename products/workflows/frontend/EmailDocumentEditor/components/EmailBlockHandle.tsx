import type { Editor } from '@tiptap/core'
import { NodeSelection } from '@tiptap/pm/state'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconCopy, IconDrag, IconEllipsis, IconTrash } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { EmailBlockAt, blockAtPos, deleteBlock, duplicateBlock, moveBlock } from '../emailCommands'
import { useEscapeToClose } from './useEscapeToClose'

interface HandlePosition {
    top: number
    left: number
    pos: number
}

/** The hover handle beside each block: drag to reorder, or open its menu. Also reachable with Alt+Arrow keys. */
export function EmailBlockHandle({
    editor,
    container,
}: {
    editor: Editor
    container: HTMLElement | null
}): JSX.Element | null {
    const [position, setPosition] = useState<HandlePosition | null>(null)
    const [menuOpen, setMenuOpen] = useState(false)
    useEscapeToClose(menuOpen, () => setMenuOpen(false))
    const positionRef = useRef(position)
    positionRef.current = position
    const menuOpenRef = useRef(menuOpen)
    menuOpenRef.current = menuOpen

    const currentBlock = useCallback((): EmailBlockAt | null => {
        const pos = positionRef.current?.pos
        return pos === undefined ? null : blockAtPos(editor.state.doc, pos)
    }, [editor])

    useEffect(() => {
        if (!container) {
            return
        }
        const onMove = (event: MouseEvent): void => {
            if (menuOpenRef.current || (event.target as HTMLElement).closest?.('[data-email-handle]')) {
                return
            }
            const { view } = editor
            const editorRect = view.dom.getBoundingClientRect()
            // The gutter beside the text counts as hovering that line, so the handle stays reachable.
            const x = Math.min(Math.max(event.clientX, editorRect.left + 2), editorRect.right - 2)
            const found = view.posAtCoords({ left: x, top: event.clientY })
            const block = found ? blockAtPos(editor.state.doc, found.inside >= 0 ? found.inside : found.pos) : null
            const dom = block ? (view.nodeDOM(block.pos) as HTMLElement | null) : null
            if (!block || !dom || !dom.getBoundingClientRect || event.clientY > editorRect.bottom + 8) {
                setPosition(null)
                return
            }
            const rect = dom.getBoundingClientRect()
            const parent = container.getBoundingClientRect()
            setPosition({
                top: rect.top - parent.top + container.scrollTop,
                left: rect.left - parent.left + container.scrollLeft - 26,
                pos: block.pos,
            })
        }
        const onLeave = (): void => {
            if (!menuOpenRef.current) {
                setPosition(null)
            }
        }
        container.addEventListener('mousemove', onMove)
        container.addEventListener('mouseleave', onLeave)
        return () => {
            container.removeEventListener('mousemove', onMove)
            container.removeEventListener('mouseleave', onLeave)
        }
    }, [container, editor])

    useEffect(() => {
        const hide = (): void => setPosition(null)
        editor.on('update', hide)
        return () => {
            editor.off('update', hide)
        }
    }, [editor])

    if (!position) {
        return null
    }

    const onDragStart = (event: React.DragEvent): void => {
        const block = currentBlock()
        if (!block) {
            event.preventDefault()
            return
        }
        const { view, state } = editor
        const selection = NodeSelection.create(state.doc, block.pos)
        view.dispatch(state.tr.setSelection(selection))
        const slice = selection.content()
        const { dom, text } = view.serializeForClipboard(slice)
        event.dataTransfer.clearData()
        event.dataTransfer.setData('text/html', dom.innerHTML)
        event.dataTransfer.setData('text/plain', text)
        event.dataTransfer.effectAllowed = 'copyMove'
        const blockDom = view.nodeDOM(block.pos) as HTMLElement | null
        if (blockDom) {
            event.dataTransfer.setDragImage(blockDom, 0, 0)
        }
        view.dragging = { slice, move: true }
    }

    return (
        <div
            data-email-handle
            className="absolute z-10 flex items-center rounded border bg-surface-primary shadow-sm"
            style={{ top: position.top + 4, left: position.left - 22 }}
            contentEditable={false}
        >
            <LemonMenu
                visible={menuOpen}
                onVisibilityChange={setMenuOpen}
                placement="bottom-start"
                items={[
                    {
                        label: 'Move up',
                        'data-attr': 'email-editor-block-move-up',
                        onClick: () => {
                            const block = currentBlock()
                            block && moveBlock(editor, block, -1)
                        },
                    },
                    {
                        label: 'Move down',
                        'data-attr': 'email-editor-block-move-down',
                        onClick: () => {
                            const block = currentBlock()
                            block && moveBlock(editor, block, 1)
                        },
                    },
                    {
                        label: 'Duplicate',
                        icon: <IconCopy />,
                        'data-attr': 'email-editor-block-duplicate',
                        onClick: () => {
                            const block = currentBlock()
                            block && duplicateBlock(editor, block)
                        },
                    },
                    {
                        label: 'Delete',
                        icon: <IconTrash />,
                        status: 'danger',
                        'data-attr': 'email-editor-block-delete',
                        onClick: () => {
                            const block = currentBlock()
                            block && deleteBlock(editor, block)
                        },
                    },
                ]}
            >
                <LemonButton
                    size="xsmall"
                    icon={<IconEllipsis />}
                    aria-label="Block options"
                    tooltip="Block options"
                    data-attr="email-editor-block-menu"
                />
            </LemonMenu>
            {/* Mouse only: the menu has the same moves for the keyboard, and so do Alt+Arrow keys. */}
            <div
                draggable
                aria-hidden
                title="Drag to move"
                className="cursor-grab text-secondary flex items-center justify-center w-5 h-6 rounded hover:bg-fill-button-tertiary-hover"
                onDragStart={onDragStart}
                onDragEnd={() => {
                    editor.view.dragging = null
                }}
                data-attr="email-editor-block-handle"
            >
                <IconDrag />
            </div>
        </div>
    )
}
