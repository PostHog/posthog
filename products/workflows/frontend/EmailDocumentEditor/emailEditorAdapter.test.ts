import { Editor } from '@tiptap/core'

import { EmailBlockKeymap } from './emailCanvasPlugins'
import { emailDocumentFromValue } from './emailDocument'
import { createEmailEditorAdapter, designForDocument } from './emailEditorAdapter'
import { buildEmailExtensions } from './emailExtensions'
import * as renderEmailHtmlModule from './renderEmailHtml'
import { unlayerToEmailDocument } from './unlayerToEmailDocument'

jest.mock('./components/EmailHtmlBlockView', () => ({ EmailHtmlBlockView: () => null }))
jest.mock('./components/EmailImageBlockView', () => ({ EmailImageBlockView: () => null }))
jest.mock('./components/EmailVariableChip', () => ({ EmailVariableChip: () => null }))

describe('emailEditorAdapter', () => {
    it.each([
        ['without sections stays readable by every editor', { type: 'paragraph' }, 1],
        [
            'with a section is not read by an editor from before sections, which would open it empty',
            { type: 'emailSection', content: [{ type: 'paragraph' }] },
            2,
        ],
    ])('a document %s', (_, block, version) => {
        const doc = { type: 'doc', content: [{ type: 'horizontalRule' }, block] }
        const design = designForDocument(doc, '<p>a</p>')

        expect(design?.emailDocument.version).toBe(version)
        expect(emailDocumentFromValue({ html: '<p>a</p>', design }).document?.doc).toEqual(doc)
    })

    it('opens as one HTML block holding the stored html in an editor that cannot read its document', () => {
        const doc = {
            type: 'doc',
            content: [
                { type: 'emailSection', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Boxed' }] }] },
            ],
        }
        const html = renderEmailHtmlModule.renderEmailHtml(doc)

        const opened = unlayerToEmailDocument(designForDocument(doc, html), html).document?.doc
        expect(opened?.content).toMatchObject([{ type: 'emailHtml', attrs: { html } }])
        expect(renderEmailHtmlModule.renderEmailHtml(opened!)).toBe(html)
    })

    it('keeps the page style when a saved document loads into an open editor', () => {
        const editor = new Editor({ extensions: buildEmailExtensions('') })
        const adapter = createEmailEditorAdapter(editor)
        const doc = {
            type: 'doc',
            attrs: { page: { bodyWidth: 560 } },
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }],
        }

        adapter.loadDocument(doc)

        expect(editor.getJSON().attrs?.page).toEqual({ bodyWidth: 560 })
        expect(editor.getText()).toEqual('Hello')
        editor.destroy()
    })

    it('reports a real edit but not the empty last paragraph a first click adds', () => {
        const editor = new Editor({
            extensions: buildEmailExtensions(''),
            content: {
                type: 'doc',
                content: [
                    { type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] },
                    { type: 'horizontalRule' },
                ],
            },
        })
        const adapter = createEmailEditorAdapter(editor)
        const onUpdated = jest.fn()
        adapter.addEventListener('design:updated', onUpdated)

        editor.commands.setTextSelection(3)

        expect(editor.getJSON().content?.at(-1)?.type).toEqual('paragraph')
        expect(onUpdated).not.toHaveBeenCalled()

        editor.commands.insertContent('!')

        expect(onUpdated).toHaveBeenCalledTimes(1)
        editor.destroy()
    })

    it.each([
        ['selects the text of the block being edited first', 1, 'Second line'],
        ['selects the whole email on a second press', 2, 'First lineSecond line'],
    ])('Ctrl+A %s', (_, presses, selected) => {
        const editor = new Editor({
            extensions: [...buildEmailExtensions(''), EmailBlockKeymap],
            content: {
                type: 'doc',
                content: [
                    { type: 'paragraph', content: [{ type: 'text', text: 'First line' }] },
                    { type: 'paragraph', content: [{ type: 'text', text: 'Second line' }] },
                ],
            },
        })
        editor.commands.setTextSelection(15)
        for (let press = 0; press < presses; press++) {
            editor.view.someProp('handleKeyDown', (handler) =>
                handler(editor.view, new KeyboardEvent('keydown', { key: 'a', ctrlKey: true }))
            )
        }
        const { from, to } = editor.state.selection

        expect(editor.state.doc.textBetween(from, to)).toEqual(selected)
        editor.destroy()
    })

    it('Ctrl+A treats a press after leaving and coming back to an empty line as a first press', () => {
        const editor = new Editor({
            extensions: [...buildEmailExtensions(''), EmailBlockKeymap],
            content: {
                type: 'doc',
                content: [
                    { type: 'paragraph', content: [{ type: 'text', text: 'First line' }] },
                    { type: 'paragraph' },
                    { type: 'paragraph', content: [{ type: 'text', text: 'Second line' }] },
                ],
            },
        })
        const press = (): void => {
            editor.view.someProp('handleKeyDown', (handler) =>
                handler(editor.view, new KeyboardEvent('keydown', { key: 'a', ctrlKey: true }))
            )
        }
        editor.commands.setTextSelection(13)
        press()
        editor.commands.setTextSelection(3)
        editor.commands.setTextSelection(13)
        press()
        const { from, to } = editor.state.selection

        expect(editor.state.doc.textBetween(from, to)).toEqual('')
        editor.destroy()
    })

    it.each([
        ['keeps the cursor on an empty line on the first press', 1, ''],
        ['selects the whole email from an empty line on a second press', 2, 'First lineSecond line'],
    ])('Ctrl+A %s', (_, presses, selected) => {
        const editor = new Editor({
            extensions: [...buildEmailExtensions(''), EmailBlockKeymap],
            content: {
                type: 'doc',
                content: [
                    { type: 'paragraph', content: [{ type: 'text', text: 'First line' }] },
                    { type: 'paragraph' },
                    { type: 'paragraph', content: [{ type: 'text', text: 'Second line' }] },
                ],
            },
        })
        editor.commands.setTextSelection(13)
        for (let press = 0; press < presses; press++) {
            editor.view.someProp('handleKeyDown', (handler) =>
                handler(editor.view, new KeyboardEvent('keydown', { key: 'a', ctrlKey: true }))
            )
        }
        const { from, to } = editor.state.selection

        expect(editor.state.doc.textBetween(from, to)).toEqual(selected)
        editor.destroy()
    })

    it('falls back to the html text when the text part fails, so the edit still saves', () => {
        const editor = new Editor({
            extensions: buildEmailExtensions(''),
            content: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }] },
        })
        const adapter = createEmailEditorAdapter(editor)
        const renderText = jest.spyOn(renderEmailHtmlModule, 'renderEmailText').mockImplementation(() => {
            throw new Error('text failed')
        })
        const callback = jest.fn()

        adapter.exportPlainText(callback)

        expect(callback).toHaveBeenCalledWith({ text: 'Hello' })
        renderText.mockRestore()
        editor.destroy()
    })
})
