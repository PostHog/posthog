import type { Editor, JSONContent } from '@tiptap/core'
import { NodeSelection } from '@tiptap/pm/state'
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
    const inline: JSONContent[] = [
        { type: 'variable', attrs: { expression, fallback: '' } },
        { type: 'text', text: ' ' },
    ]
    const { selection } = editor.state
    // With a block selected, inserting would replace the block.
    if (selection instanceof NodeSelection && selection.node.isBlock) {
        insertBlock(editor, { type: 'paragraph', content: inline })
        return
    }
    editor.chain().focus().insertContent(inline).run()
}
