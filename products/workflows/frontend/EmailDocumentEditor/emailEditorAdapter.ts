import type { Editor, EditorEvents } from '@tiptap/core'

import {
    EMAIL_DOCUMENT_DESIGN_KEY,
    EMAIL_DOCUMENT_VERSION,
    EmailDocument,
    emailDocumentFromValue,
    isEmailDocEmpty,
} from './emailDocument'
import { emailDocumentToUnlayer } from './emailDocumentToUnlayer'
import { renderEmailHtml, renderEmailText, safeEmailDoc } from './renderEmailHtml'
import { unlayerToEmailDocument } from './unlayerToEmailDocument'

type Listener = () => void

/**
 * The saved form of a document: the same email as an old-editor design, so it stays editable there if the new editor
 * is turned off, with the document and the html it rendered alongside it.
 */
export function designForDocument(doc: Record<string, any>, html: string): Record<string, any> | null {
    if (isEmailDocEmpty(doc)) {
        return null
    }
    const document: EmailDocument = { version: EMAIL_DOCUMENT_VERSION, doc, html }
    return { ...emailDocumentToUnlayer(doc), [EMAIL_DOCUMENT_DESIGN_KEY]: document }
}

/**
 * The first selection in a document that ends in a block other than a paragraph makes the editor add an empty last
 * paragraph, and that fires `update`. A click isn't an edit: treating it as one would let a save replace a converted
 * email that nobody changed.
 */
export function isDocumentEdit({ transaction }: EditorEvents['update']): boolean {
    return transaction.docChanged
}

/**
 * Gives `emailTemplaterLogic` the part of Unlayer's editor API it calls, so everything it does around saving
 * (no-op saves, debounced live changes, external edits, save as template) works the same for both editors.
 */
export function createEmailEditorAdapter(editor: Editor): Record<string, any> {
    const listeners: Record<string, Listener[]> = {}
    const emit = (type: string): void => (listeners[type] ?? []).forEach((listener) => listener())

    const onUpdate = (event: EditorEvents['update']): void => {
        if (isDocumentEdit(event)) {
            emit('design:updated')
        }
    }
    // setContent replaces the blocks but not the document's own attributes, which hold the page style.
    const loadDoc = (doc: Record<string, any>): void => {
        editor
            .chain()
            .setMeta('addToHistory', false)
            .setContent(safeEmailDoc(doc), { emitUpdate: false })
            .command(({ tr }) => {
                tr.setDocAttribute('page', doc.attrs?.page ?? {})
                return true
            })
            .run()
    }
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
        loadDesign: (design: Record<string, any>, html?: string) => {
            const wrappedHtml = design?.body?.rows?.[0]?.columns?.[0]?.contents?.[0]?.values?.html
            const savedHtml = design?.[EMAIL_DOCUMENT_DESIGN_KEY]?.html ?? wrappedHtml
            const { document } = emailDocumentFromValue({ design, html: html ?? savedHtml })
            // An old-editor template applied to an open email has to show here too.
            const doc = document?.doc ?? unlayerToEmailDocument(design, html ?? wrappedHtml).document?.doc
            if (doc) {
                loadDoc(doc)
                emit('design:loaded')
            }
        },
        loadDocument: (doc: Record<string, any>) => {
            loadDoc(doc)
            emit('design:loaded')
        },
        setMergeTags: () => {},
        registerProvider: () => {},
        registerCallback: () => {},
        destroy: () => {
            editor.off('update', onUpdate)
        },
    }
}
