import type { Editor } from '@tiptap/core'
import { useState } from 'react'

import { IconImage, IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu, Popover } from '@posthog/lemon-ui'

import { IconTextSize } from 'lib/lemon-ui/icons'

import { EMAIL_BLOCK_OPTIONS, EmailBlockOption } from '../emailBlockCatalog'
import { useEmailEditorContext } from '../emailEditorContext'
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
            <LemonButton
                {...SQUARE_BUTTON}
                icon={<IconTextSize />}
                tooltip="Text"
                aria-label="Add text"
                data-attr="email-editor-insert-text"
                onClick={() => insert(byKey('paragraph'))}
            />
            <LemonButton
                {...SQUARE_BUTTON}
                icon={<IconImage />}
                tooltip="Image"
                aria-label="Add image"
                data-attr="email-editor-insert-image"
                onClick={() => insert(byKey('image'))}
            />
            <LemonMenu
                placement="right-start"
                visible={blocksOpen}
                onVisibilityChange={setBlocksOpen}
                items={EMAIL_BLOCK_OPTIONS.filter((option) => option.key !== 'paragraph' && option.key !== 'image').map(
                    (option) => ({
                        label: option.title,
                        icon: option.icon,
                        'data-attr': `email-editor-insert-${option.key}`,
                        onClick: () => insert(option),
                    })
                )}
            >
                <LemonButton
                    {...SQUARE_BUTTON}
                    icon={<IconPlus />}
                    tooltip={blocksOpen ? undefined : 'More blocks'}
                    aria-label="More blocks"
                    data-attr="email-editor-insert-more"
                    sideIcon={null}
                />
            </LemonMenu>
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
