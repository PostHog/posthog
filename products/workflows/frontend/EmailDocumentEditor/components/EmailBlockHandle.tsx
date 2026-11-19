import type { Editor } from '@tiptap/core'
import { NodeSelection } from '@tiptap/pm/state'
import clsx from 'clsx'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconCopy, IconDrag, IconEllipsis, IconTrash } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

import { EmailBlockAt, blockAtPos, deleteBlock, duplicateBlock, moveBlock } from '../emailCommands'
import { trackDrag } from '../emailDragDrop'
import { useEscapeToClose } from './useEscapeToClose'

const HANDLE_GAP = 8

interface HandlePosition {
    top: number
    left: number
    above: boolean
    width: number
    height: number
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
            // Beside a block in a later column it would cover the column to its left, so it sits on top instead.
            const column = dom.parentElement?.closest('.email-canvas-column')
            setPosition({
                top: rect.top - parent.top + container.scrollTop,
                left: rect.left - parent.left + container.scrollLeft - HANDLE_GAP,
                above: !!column?.previousElementSibling,
                width: rect.width,
                height: rect.height,
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
    const menuBlock = menuOpen ? currentBlock() : null

    const onDragStart = (event: React.DragEvent): void => {
        const block = currentBlock()
        if (!block) {
            event.preventDefault()
            return
        }
        const { view, state } = editor
        // Carried on the drag rather than selected, because selecting focuses the editor and that cancels a drag
        // started before anyone has clicked into it.
        const node = NodeSelection.create(state.doc, block.pos)
        const slice = node.content()
        const { dom, text } = view.serializeForClipboard(slice)
        event.dataTransfer.clearData()
        event.dataTransfer.setData('text/html', dom.innerHTML)
        event.dataTransfer.setData('text/plain', text)
        event.dataTransfer.effectAllowed = 'copyMove'
        const blockDom = view.nodeDOM(block.pos) as HTMLElement | null
        if (blockDom) {
            const rect = blockDom.getBoundingClientRect()
            event.dataTransfer.setDragImage(blockDom, 0, Math.min(Math.max(event.clientY - rect.top, 0), rect.height))
        }
        // The editor's drop reads `node`, though its type leaves it out.
        view.dragging = { slice, move: true, node } as typeof view.dragging
        trackDrag(editor, slice, block.pos)
    }

    return (
        <>
            <div
                aria-hidden
                className="EmailDocumentEditor__block-outline"
                style={{
                    top: position.top,
                    left: position.left + HANDLE_GAP,
                    width: position.width,
                    height: position.height,
                }}
            />
            <div
                data-email-handle
                className={clsx(
                    'absolute z-10 flex items-center rounded border bg-surface-primary shadow-sm',
                    position.above ? '-translate-y-full' : '-translate-x-full'
                )}
                style={
                    position.above
                        ? { top: position.top, left: position.left + HANDLE_GAP }
                        : { top: position.top + 4, left: position.left }
                }
                contentEditable={false}
            >
                <LemonMenu
                    visible={menuOpen}
                    onVisibilityChange={setMenuOpen}
                    placement="bottom-start"
                    items={[
                        {
                            label: 'Move up',
                            icon: <IconArrowUp />,
                            disabledReason: menuBlock && menuBlock.index === 0 ? 'Already at the top' : undefined,
                            'data-attr': 'email-editor-block-move-up',
                            onClick: () => {
                                const block = currentBlock()
                                block && moveBlock(editor, block, -1)
                            },
                        },
                        {
                            label: 'Move down',
                            icon: <IconArrowDown />,
                            disabledReason:
                                menuBlock && menuBlock.index === menuBlock.parent.childCount - 1
                                    ? 'Already at the bottom'
                                    : undefined,
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
                    data-attr="email-editor-block-handle"
                >
                    <IconDrag />
                </div>
            </div>
        </>
    )
}
