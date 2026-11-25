import type { Editor } from '@tiptap/core'

import { LemonButton } from '@posthog/lemon-ui'

import { EmailBlockOption } from '../emailBlockCatalog'
import { startBlockOptionDrag } from '../emailDragDrop'

export function EmailBlockPalette({
    editor,
    options,
    onInsert,
    onDragStart,
    onDragEnd,
}: {
    editor: Editor
    options: EmailBlockOption[]
    onInsert: (option: EmailBlockOption) => void
    onDragStart: () => void
    onDragEnd: () => void
}): JSX.Element {
    return (
        <div className="w-96 p-1" data-attr="email-editor-block-palette">
            <div className="px-1 pb-1 text-xs text-secondary">Click to add, or drag into the email</div>
            <div className="grid grid-cols-2 gap-0.5">
                {options.map((option) => (
                    <div
                        key={option.key}
                        draggable
                        onDragStart={(event) => {
                            onDragStart()
                            startBlockOptionDrag(editor, option, event, onDragEnd)
                        }}
                    >
                        <LemonButton
                            size="small"
                            fullWidth
                            icon={option.icon}
                            onClick={() => onInsert(option)}
                            data-attr={`email-editor-insert-${option.key}`}
                        >
                            {option.title}
                        </LemonButton>
                    </div>
                ))}
            </div>
        </div>
    )
}
