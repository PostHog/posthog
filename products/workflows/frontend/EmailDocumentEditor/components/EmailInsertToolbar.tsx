import type { Editor } from '@tiptap/core'

import { IconImage, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { IconTextSize } from 'lib/lemon-ui/icons'

import { EMAIL_BLOCK_OPTIONS, EmailBlockOption } from '../emailBlockCatalog'
import { useEmailEditorContext } from '../emailEditorContext'
import { insertBlockOption, insertVariableAtCursor } from './emailEditorActions'

export function EmailInsertToolbar({ editor }: { editor: Editor }): JSX.Element {
    const { pickImage, variableOptions } = useEmailEditorContext()
    const insert = (option: EmailBlockOption): void => insertBlockOption(editor, option, pickImage)
    const byKey = (key: string): EmailBlockOption => EMAIL_BLOCK_OPTIONS.find((option) => option.key === key)!

    const groups = Object.entries(
        variableOptions.reduce<Record<string, typeof variableOptions>>((all, option) => {
            all[option.group] = [...(all[option.group] ?? []), option]
            return all
        }, {})
    )

    return (
        <div
            className="flex flex-col gap-1 p-1 border rounded bg-surface-primary shadow-sm"
            role="toolbar"
            aria-label="Add to email"
            data-attr="email-editor-insert-toolbar"
        >
            <LemonButton
                size="small"
                icon={<IconTextSize />}
                tooltip="Text"
                aria-label="Add text"
                tooltipPlacement="right"
                data-attr="email-editor-insert-text"
                onClick={() => insert(byKey('paragraph'))}
            />
            <LemonButton
                size="small"
                icon={<IconImage />}
                tooltip="Image"
                aria-label="Add image"
                tooltipPlacement="right"
                data-attr="email-editor-insert-image"
                onClick={() => insert(byKey('image'))}
            />
            <LemonMenu
                placement="right-start"
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
                    size="small"
                    icon={<IconPlusSmall />}
                    tooltip="More blocks"
                    aria-label="More blocks"
                    tooltipPlacement="right"
                    data-attr="email-editor-insert-more"
                    sideIcon={null}
                />
            </LemonMenu>
            <LemonMenu
                placement="right-start"
                items={groups.map(([group, options]) => ({
                    title: group,
                    items: options.slice(0, 40).map((option) => ({
                        label: option.label,
                        'data-attr': 'email-editor-insert-variable-option',
                        onClick: () => insertVariableAtCursor(editor, option.expression),
                    })),
                }))}
            >
                <LemonButton
                    size="small"
                    tooltip="Variables"
                    aria-label="Add a variable"
                    tooltipPlacement="right"
                    data-attr="email-editor-insert-variable"
                    sideIcon={null}
                >
                    <span className="font-mono text-xs px-0.5" translate="no">
                        {'{x}'}
                    </span>
                </LemonButton>
            </LemonMenu>
        </div>
    )
}
