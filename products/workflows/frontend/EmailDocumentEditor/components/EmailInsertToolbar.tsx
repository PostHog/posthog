import type { Editor } from '@tiptap/core'
import { useState } from 'react'

import { IconImage, IconPlus } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import { IconTextSize } from 'lib/lemon-ui/icons'

import { EMAIL_BLOCK_OPTIONS, EmailBlockOption } from '../emailBlockCatalog'
import { startBlockOptionDrag } from '../emailDragDrop'
import { useEmailEditorContext } from '../emailEditorContext'
import { EmailBlockPalette } from './EmailBlockPalette'
import { insertBlockOption, insertVariableAtCursor } from './emailEditorActions'
import { EmailVariablePicker } from './EmailVariablePicker'
import { useEscapeToClose } from './useEscapeToClose'

const SQUARE_BUTTON = {
    size: 'small',
    noPadding: true,
    center: true,
    className: 'EmailEditor__square-button',
    tooltipPlacement: 'right',
} as const

export function EmailInsertToolbar({ editor }: { editor: Editor }): JSX.Element {
    const { pickImage, variableOptions } = useEmailEditorContext()
    const [blocksOpen, setBlocksOpen] = useState(false)
    const [draggingBlock, setDraggingBlock] = useState(false)
    const [variablesOpen, setVariablesOpen] = useState(false)
    useEscapeToClose(blocksOpen, () => setBlocksOpen(false))
    useEscapeToClose(variablesOpen, () => {
        setVariablesOpen(false)
        editor.commands.focus()
    })
    const insert = (option: EmailBlockOption): void => insertBlockOption(editor, option, pickImage)
    const byKey = (key: string): EmailBlockOption => EMAIL_BLOCK_OPTIONS.find((option) => option.key === key)!

    return (
        <div
            className="flex flex-col items-center gap-1 p-1 border rounded bg-surface-primary shadow-sm"
            role="toolbar"
            aria-label="Add to email"
            data-attr="email-editor-insert-toolbar"
        >
            <div draggable onDragStart={(event) => startBlockOptionDrag(editor, byKey('paragraph'), event)}>
                <LemonButton
                    {...SQUARE_BUTTON}
                    icon={<IconTextSize />}
                    tooltip="Text, or drag into the email"
                    aria-label="Add text"
                    data-attr="email-editor-insert-text"
                    onClick={() => insert(byKey('paragraph'))}
                />
            </div>
            <div draggable onDragStart={(event) => startBlockOptionDrag(editor, byKey('image'), event)}>
                <LemonButton
                    {...SQUARE_BUTTON}
                    icon={<IconImage />}
                    tooltip="Image, or drag into the email"
                    aria-label="Add image"
                    data-attr="email-editor-insert-image"
                    onClick={() => insert(byKey('image'))}
                />
            </div>
            <Popover
                visible={blocksOpen}
                onClickOutside={() => setBlocksOpen(false)}
                placement="right-start"
                // Out of the way while a block is dragged from it, so the email underneath can take the drop.
                className={draggingBlock ? 'opacity-0 pointer-events-none' : undefined}
                overlay={
                    <EmailBlockPalette
                        editor={editor}
                        options={EMAIL_BLOCK_OPTIONS.filter(
                            (option) => option.key !== 'paragraph' && option.key !== 'image'
                        )}
                        onInsert={(option) => {
                            setBlocksOpen(false)
                            insert(option)
                        }}
                        onDragStart={() => setDraggingBlock(true)}
                        onDragEnd={() => {
                            setDraggingBlock(false)
                            setBlocksOpen(false)
                        }}
                    />
                }
            >
                <LemonButton
                    {...SQUARE_BUTTON}
                    icon={<IconPlus />}
                    active={blocksOpen}
                    tooltip={blocksOpen ? undefined : 'More blocks'}
                    aria-label="More blocks"
                    aria-expanded={blocksOpen}
                    data-attr="email-editor-insert-more"
                    sideIcon={null}
                    onClick={() => setBlocksOpen(!blocksOpen)}
                />
            </Popover>
            <Popover
                visible={variablesOpen}
                onClickOutside={() => setVariablesOpen(false)}
                placement="right-start"
                overlay={
                    <EmailVariablePicker
                        options={variableOptions}
                        onPick={(option) => {
                            setVariablesOpen(false)
                            insertVariableAtCursor(editor, option.expression)
                        }}
                    />
                }
            >
                <LemonButton
                    {...SQUARE_BUTTON}
                    active={variablesOpen}
                    sideIcon={null}
                    tooltip={variablesOpen ? undefined : 'Variables'}
                    aria-label="Add a variable"
                    data-attr="email-editor-insert-variable"
                    onClick={() => setVariablesOpen(!variablesOpen)}
                >
                    <span className="font-mono text-xs" translate="no">
                        {'{x}'}
                    </span>
                </LemonButton>
            </Popover>
        </div>
    )
}
