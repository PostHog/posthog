import type { Editor } from '@tiptap/core'

import { buildHtmlWrapDesign } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import {
    EMAIL_DOCUMENT_DESIGN_KEY,
    EMAIL_DOCUMENT_VERSION,
    EmailDocument,
    emailDocumentFromValue,
    isEmailDocEmpty,
} from './emailDocument'
import { renderEmailHtml, renderEmailText } from './renderEmailHtml'

type Listener = () => void

/** The saved form of a document: an old-editor design showing the rendered html, with the document alongside it. */
export function designForDocument(doc: Record<string, any>, html: string): Record<string, any> | null {
    if (isEmailDocEmpty(doc)) {
        return null
    }
    const document: EmailDocument = { version: EMAIL_DOCUMENT_VERSION, doc }
    return { ...(buildHtmlWrapDesign(html) as Record<string, any>), [EMAIL_DOCUMENT_DESIGN_KEY]: document }
}

/**
 * Gives `emailTemplaterLogic` the part of Unlayer's editor API it calls, so everything it does around saving
 * (no-op saves, debounced live changes, external edits, save as template) works the same for both editors.
 */
export function createEmailEditorAdapter(editor: Editor): Record<string, any> {
    const listeners: Record<string, Listener[]> = {}
    const emit = (type: string): void => (listeners[type] ?? []).forEach((listener) => listener())

    const onUpdate = (): void => emit('design:updated')
    editor.on('update', onUpdate)

    return {
        addEventListener: (type: string, listener: Listener) => {
            listeners[type] = [...(listeners[type] ?? []), listener]
        },
        exportHtml: (callback: (data: { html: string; design: any }) => void) => {
            const doc = editor.getJSON()
            const html = renderEmailHtml(doc)
            callback({ html, design: designForDocument(doc, html) })
        },
        exportPlainText: (callback: (data: { text: string }) => void) => {
            callback({ text: renderEmailText(editor.getJSON()) })
        },
        loadDesign: (design: Record<string, any>) => {
            const { document } = emailDocumentFromValue({
                design,
                html: design?.body?.rows?.[0]?.columns?.[0]?.contents?.[0]?.values?.html,
            })
            // An old-editor design has no document to show. The logic routes those to the old editor.
            if (!document) {
                return
            }
            editor.chain().setMeta('addToHistory', false).setContent(document.doc, { emitUpdate: false }).run()
            emit('design:loaded')
        },
        notifyChanged: onUpdate,
        setMergeTags: () => {},
        registerProvider: () => {},
        registerCallback: () => {},
        destroy: () => {
            editor.off('update', onUpdate)
        },
    }
}
