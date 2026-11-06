import type { Editor, JSONContent } from '@tiptap/core'
import posthog from 'posthog-js'

import { EmailBlockOption } from '../emailBlockCatalog'
import { insertBlock } from '../emailCommands'
import type { EmailEditorContextValue } from '../emailEditorContext'

export function imageNode(image: Record<string, any>): JSONContent {
    return { type: 'emailImage', attrs: { ...image } }
}

export function insertBlockOption(
    editor: Editor,
    option: EmailBlockOption,
    pickImage: EmailEditorContextValue['pickImage']
): void {
    // pinned: analytics event name and property, renaming breaks dashboards
    posthog.capture('email editor block inserted', { block: option.key })
    if (option.needsImage) {
        pickImage((image) => insertBlock(editor, imageNode(image)))
        return
    }
    if (option.content) {
        insertBlock(editor, option.content)
    }
}

export function insertVariableAtCursor(editor: Editor, expression: string): void {
    editor
        .chain()
        .focus()
        .insertContent([
            { type: 'variable', attrs: { expression, fallback: '' } },
            { type: 'text', text: ' ' },
        ])
        .run()
}
