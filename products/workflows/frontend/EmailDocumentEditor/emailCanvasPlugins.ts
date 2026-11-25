import { Extension } from '@tiptap/core'
import { NodeSelection, Plugin, PluginKey, Selection, TextSelection } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

import { blockAtPos, moveBlock } from './emailCommands'
import { safeEmailVisibility } from './renderEmailHtml'

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

/** How a block's visibility reads on its badge, such as "Only if Paying customers · Hidden on phones". */
export function visibilityLabel(raw: unknown): string {
    const visibility = safeEmailVisibility(raw)
    if (!visibility) {
        return ''
    }
    return [
        visibility.condition &&
            `Only if ${visibility.condition.label || visibility.condition.before.replace(/^\{%-?\s*(if|unless)\s*|\s*-?%\}$/g, '')}`,
        visibility.hideDesktop && 'Hidden on desktop',
        visibility.hideMobile && 'Hidden on phones',
    ]
        .filter(Boolean)
        .join(' · ')
}

/** Blocks that not everyone sees get a badge, so the canvas doesn't pass them off as part of every email. */
export const EmailVisibilityBadges = Extension.create({
    name: 'emailVisibilityBadges',
    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey('emailVisibilityBadges'),
                props: {
                    decorations: (state) => {
                        const decorations: Decoration[] = []
                        state.doc.descendants((node, pos) => {
                            const label = visibilityLabel(node.attrs.emailVisibility)
                            if (label) {
                                decorations.push(
                                    Decoration.node(pos, pos + node.nodeSize, {
                                        class: 'email-canvas-conditional',
                                        'data-visibility-label': label,
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

function isHtmlBlockSelected(selection: Selection): boolean {
    return selection instanceof NodeSelection && selection.node.type.name === 'emailHtml'
}

export const EmailBlockKeymap = Extension.create({
    name: 'emailBlockKeymap',
    addKeyboardShortcuts() {
        const move = (direction: -1 | 1) => () => {
            const block = blockAtPos(this.editor.state.doc, this.editor.state.selection.from)
            return block ? moveBlock(this.editor, block, direction) : false
        }
        // The first press selects the text of the block being edited, as most editors do, so a delete right after it
        // can't take the whole email. A second press selects everything.
        let firstPress: Selection | null = null
        // Any edit or cursor move replaces the selection, so only an immediate second press matches it.
        const keepsSelection = (selection: Selection): boolean => {
            const isSecondPress = firstPress === selection
            firstPress = isSecondPress ? null : selection
            return !isSecondPress
        }
        const selectBlockText = (): boolean => {
            const { selection, tr } = this.editor.state
            const { $from, $to } = selection
            if (selection instanceof NodeSelection && selection.node.isBlock) {
                return keepsSelection(selection)
            }
            if (!$from.parent.isTextblock || !$from.sameParent($to)) {
                return false
            }
            const start = $from.start()
            const end = $from.end()
            // An empty block has nothing to select, so the first press there keeps the cursor where it is.
            if (start === end) {
                return keepsSelection(selection)
            }
            firstPress = null
            if (selection.from === start && selection.to === end) {
                return false
            }
            this.editor.view.dispatch(tr.setSelection(TextSelection.create(tr.doc, start, end)))
            return true
        }
        return { 'Alt-ArrowUp': move(-1), 'Alt-ArrowDown': move(1), 'Mod-a': selectBlockText }
    },
    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey('emailClickOutOfNode'),
                props: {
                    // A key pressed on a selected HTML block would replace it, and an imported email is one whole block.
                    handleTextInput: (view) => isHtmlBlockSelected(view.state.selection),
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
