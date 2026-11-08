import { Editor, Extension } from '@tiptap/core'
import { Fragment, Slice } from '@tiptap/pm/model'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { dropPoint } from '@tiptap/pm/transform'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import posthog from 'posthog-js'

import { EmailBlockOption } from './emailBlockCatalog'
import { selectInserted } from './emailCommands'

const DRAGGING_CLASS = 'EmailDocumentCanvas--dragging'
const dragSourceKey = new PluginKey<number | null>('emailDragSource')
let draggingNewBlock = false

/** Dims the block being dragged. A decoration, because the editor rebuilds a block whose DOM is changed directly. */
export const EmailDragSource = Extension.create({
    name: 'emailDragSource',
    addProseMirrorPlugins() {
        const editor = this.editor
        return [
            new Plugin<number | null>({
                key: dragSourceKey,
                state: {
                    init: () => null,
                    apply: (tr, pos) => {
                        const meta = tr.getMeta(dragSourceKey)
                        return meta !== undefined ? meta : tr.docChanged ? null : pos
                    },
                },
                props: {
                    // The editor's own drop treats this as a move, which would delete the selected block.
                    handleDrop: (view, event, slice) => {
                        const node = slice.content.firstChild
                        const mouse = view.posAtCoords({ left: event.clientX, top: event.clientY })
                        if (!draggingNewBlock || !node || !mouse) {
                            return false
                        }
                        const { doc } = view.state
                        const $mouse = doc.resolve(mouse.pos)
                        const at =
                            dropPoint(doc, mouse.pos, slice) ?? ($mouse.depth ? $mouse.after(1) : doc.content.size)
                        view.dispatch(view.state.tr.insert(at, node))
                        selectInserted(editor, at)
                        return true
                    },
                    decorations: (state) => {
                        const pos = dragSourceKey.getState(state) ?? null
                        const node = pos === null ? null : state.doc.nodeAt(pos)
                        return node && pos !== null
                            ? DecorationSet.create(state.doc, [
                                  Decoration.node(pos, pos + node.nodeSize, { class: 'email-canvas-drag-source' }),
                              ])
                            : null
                    },
                },
            }),
        ]
    },
})

function setDragSource(editor: Editor, pos: number | null): void {
    editor.view.dispatch(editor.state.tr.setMeta(dragSourceKey, pos).setMeta('addToHistory', false))
}

function canvasOf(editor: Editor): HTMLElement | null {
    return editor.view.dom.closest('.EmailDocumentCanvas')
}

/**
 * Shows the canvas as a drop target until the drag ends. Listens on the window, because the drag can start outside
 * the editor and its source can unmount before the drag ends.
 */
export function trackDrag(
    editor: Editor,
    slice: Slice,
    sourcePos: number | null,
    onEnd?: (dropped: boolean) => void
): void {
    canvasOf(editor)?.classList.add(DRAGGING_CLASS)
    if (sourcePos !== null) {
        setDragSource(editor, sourcePos)
    }
    const end = (event: DragEvent): void => {
        window.removeEventListener('drop', end, true)
        window.removeEventListener('dragend', end, true)
        canvasOf(editor)?.classList.remove(DRAGGING_CLASS)
        const dropped = event.type === 'drop' && editor.view.dom.contains(event.target as Node)
        if (!dropped) {
            // A drag ended outside the email never tells the editor, which would keep showing the drop line.
            editor.view.dom.dispatchEvent(new DragEvent('dragleave'))
        }
        // The editor reads the slice on drop, which runs after this capture listener.
        window.setTimeout(() => {
            if (editor.view.dragging?.slice === slice) {
                editor.view.dragging = null
            }
            if (sourcePos !== null && !editor.isDestroyed) {
                setDragSource(editor, null)
            }
            onEnd?.(dropped)
        })
    }
    window.addEventListener('drop', end, true)
    window.addEventListener('dragend', end, true)
}

export function startBlockOptionDrag(
    editor: Editor,
    option: EmailBlockOption,
    event: React.DragEvent,
    onEnd?: () => void
): void {
    const content = option.needsImage ? { type: 'emailImage' } : option.content
    if (!content) {
        event.preventDefault()
        return
    }
    const slice = new Slice(Fragment.from(editor.schema.nodeFromJSON(content)), 0, 0)
    event.dataTransfer.effectAllowed = 'copy'
    event.dataTransfer.setData('text/plain', option.title)
    editor.view.dragging = { slice, move: false }
    draggingNewBlock = true
    trackDrag(editor, slice, null, (dropped) => {
        draggingNewBlock = false
        if (dropped) {
            // pinned: analytics event name and property, renaming breaks dashboards
            posthog.capture('email editor block inserted', { block: option.key, method: 'drag' })
        }
        onEnd?.()
    })
}
