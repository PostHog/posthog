import { Extension } from '@tiptap/core'
import { NodeSelection, Plugin, PluginKey, Selection } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

import { blockAtPos, moveBlock } from './emailCommands'

const LIQUID_TAG = /\{%[\s\S]*?%\}/g

/** Liquid tags stay plain text, so they're marked up visually to show they aren't part of the copy. */
export const EmailLiquidHighlight = Extension.create({
    name: 'emailLiquidHighlight',
    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey('emailLiquidHighlight'),
                props: {
                    decorations: (state) => {
                        const decorations: Decoration[] = []
                        state.doc.descendants((node, pos) => {
                            if (!node.isText || !node.text) {
                                return
                            }
                            for (const match of node.text.matchAll(LIQUID_TAG)) {
                                decorations.push(
                                    Decoration.inline(pos + match.index, pos + match.index + match[0].length, {
                                        class: 'email-canvas-liquid-tag',
                                    })
                                )
                            }
                        })
                        return DecorationSet.create(state.doc, decorations)
                    },
                },
            }),
        ]
    },
})

export const EmailBlockKeymap = Extension.create({
    name: 'emailBlockKeymap',
    addKeyboardShortcuts() {
        const move = (direction: -1 | 1) => () => {
            const block = blockAtPos(this.editor.state.doc, this.editor.state.selection.from)
            return block ? moveBlock(this.editor, block, direction) : false
        }
        return { 'Alt-ArrowUp': move(-1), 'Alt-ArrowDown': move(1) }
    },
    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey('emailClickOutOfNode'),
                props: {
                    // Chrome leaves the native selection on a selected block inside a column when the click lands
                    // elsewhere, so the block stayed selected and the next keystroke replaced it.
                    handleClick: (view, pos, event) => {
                        const { selection, doc } = view.state
                        if (!(selection instanceof NodeSelection) || (pos >= selection.from && pos <= selection.to)) {
                            return false
                        }
                        const clicked = view.posAtCoords({ left: event.clientX, top: event.clientY })
                        if (clicked && clicked.inside >= 0 && doc.nodeAt(clicked.inside)?.isAtom) {
                            return false
                        }
                        view.dispatch(view.state.tr.setSelection(Selection.near(doc.resolve(pos))))
                        return true
                    },
                },
            }),
        ]
    },
})
