import { useActions, useValues } from 'kea'
import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { cn } from '@posthog/quill-primitives'

import { fullNameOrEmail } from 'lib/utils/strings'

import { createTextCommentAnchor, resolveTextCommentAnchor } from '../artifactComments'
import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { ArtifactInlineThread, INLINE_THREAD_WIDTH_PX } from './ArtifactInlineThread'
import { ArtifactPendingComment, PENDING_COMMENT_WIDTH_PX } from './ArtifactPendingComment'

const EDGE_MARGIN_PX = 8

interface HighlightRect {
    id: string
    label: string
    left: number
    top: number
    width: number
    height: number
}

interface TextNodeIndex {
    text: string
    entries: { node: Text; start: number; end: number }[]
}

/** The text of `root` as one string, with the text node that holds each part. */
function buildTextNodeIndex(root: HTMLElement): TextNodeIndex {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    const entries: TextNodeIndex['entries'] = []
    let text = ''
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const textNode = node as Text
        const start = text.length
        text += textNode.data
        entries.push({ node: textNode, start, end: text.length })
    }
    return { text, entries }
}

function rangeFromOffsets(index: TextNodeIndex, start: number, end: number): Range | null {
    let startNode: Text | null = null
    let startOffset = 0
    for (const entry of index.entries) {
        if (!startNode && start >= entry.start && start <= entry.end) {
            startNode = entry.node
            startOffset = start - entry.start
        }
        if (startNode && end >= entry.start && end <= entry.end) {
            const range = document.createRange()
            range.setStart(startNode, startOffset)
            range.setEnd(entry.node, end - entry.start)
            return range
        }
    }
    return null
}

/** The selection as offsets into the text of `root`, the same offsets `buildTextNodeIndex` counts. */
function selectionOffsets(root: HTMLElement, range: Range): { start: number; end: number } {
    const before = document.createRange()
    before.selectNodeContents(root)
    before.setEnd(range.startContainer, range.startOffset)
    const through = document.createRange()
    through.selectNodeContents(root)
    through.setEnd(range.endContainer, range.endOffset)
    return { start: before.toString().length, end: through.toString().length }
}

// A fully selected inline element reports its own box and the boxes of its text, so the tints would stack.
// Only boxes that no other box contains stay.
function outermostRects(rects: Iterable<DOMRect>): DOMRect[] {
    const EPSILON = 0.5
    const contains = (outer: DOMRect, inner: DOMRect): boolean =>
        outer.left <= inner.left + EPSILON &&
        outer.right >= inner.right - EPSILON &&
        outer.top <= inner.top + EPSILON &&
        outer.bottom >= inner.bottom - EPSILON
    const list = Array.from(rects).filter((rect) => rect.width > 0 && rect.height > 0)
    return list.filter(
        (rect, index) =>
            !list.some(
                (other, otherIndex) =>
                    otherIndex !== index && contains(other, rect) && (otherIndex < index || !contains(rect, other))
            )
    )
}

/**
 * Text that people can select to comment on, with a tint on each open text thread. Offsets count the
 * rendered text, the same way PostHog Desktop counts them, so a highlight written in either app shows in both.
 */
export function ArtifactTextAnnotations({
    logicProps,
    selectable = true,
    children,
}: {
    logicProps: TaskArtifactCommentsLogicProps
    selectable?: boolean
    children: ReactNode
}): JSX.Element {
    const logic = taskArtifactCommentsLogic(logicProps)
    const { anchoredThreads, activeThreadId, pendingAnchor, pendingPosition } = useValues(logic)
    const { activateThread, setPendingAnchor, dismissPending } = useActions(logic)
    const containerRef = useRef<HTMLDivElement>(null)
    const rootRef = useRef<HTMLDivElement>(null)
    const [rects, setRects] = useState<HighlightRect[]>([])

    const textThreads = useMemo(
        () => anchoredThreads.filter((thread) => thread.anchor?.kind === 'text'),
        [anchoredThreads]
    )

    const recalculate = useCallback(() => {
        const root = rootRef.current
        const container = containerRef.current
        if (!root || !container) {
            return
        }
        const index = buildTextNodeIndex(root)
        const box = container.getBoundingClientRect()
        // Client rects include CSS transforms, such as the full page dialog's open animation, but the highlights
        // are placed in the container's own layout pixels. A transform does not resize the container, so no
        // observer measures again after it ends.
        const scaleX = box.width / container.offsetWidth || 1
        const scaleY = box.height / container.offsetHeight || 1
        const next: HighlightRect[] = []
        for (const thread of textThreads) {
            if (thread.anchor?.kind !== 'text') {
                continue
            }
            const resolved = resolveTextCommentAnchor(index.text, thread.anchor)
            const range = resolved ? rangeFromOffsets(index, resolved.start, resolved.end) : null
            if (!range) {
                continue
            }
            const author = thread.root.created_by ? fullNameOrEmail(thread.root.created_by) : 'Deleted user'
            for (const rect of outermostRects(range.getClientRects())) {
                next.push({
                    id: thread.root.id,
                    label: `Open comment from ${author}`,
                    left: (rect.left - box.left) / scaleX,
                    top: (rect.top - box.top) / scaleY,
                    width: rect.width / scaleX,
                    height: rect.height / scaleY,
                })
            }
        }
        setRects(next)
    }, [textThreads])

    const recalculateRef = useRef(recalculate)
    useEffect(() => {
        recalculateRef.current = recalculate
        recalculate()
    }, [recalculate])

    // Text wraps again when the pane resizes, and markdown can finish rendering after mount.
    useEffect(() => {
        const root = rootRef.current
        if (!root) {
            return
        }
        let frame = 0
        const update = (): void => {
            cancelAnimationFrame(frame)
            frame = requestAnimationFrame(() => recalculateRef.current())
        }
        const resizeObserver = new ResizeObserver(update)
        const mutationObserver = new MutationObserver(update)
        resizeObserver.observe(root)
        mutationObserver.observe(root, { childList: true, characterData: true, subtree: true })
        return () => {
            cancelAnimationFrame(frame)
            resizeObserver.disconnect()
            mutationObserver.disconnect()
        }
    }, [])

    // A pick in the comments menu scrolls its quote into view.
    useEffect(() => {
        const root = rootRef.current
        const thread = textThreads.find((candidate) => candidate.root.id === activeThreadId)
        if (!root || thread?.anchor?.kind !== 'text') {
            return
        }
        const index = buildTextNodeIndex(root)
        const resolved = resolveTextCommentAnchor(index.text, thread.anchor)
        const range = resolved ? rangeFromOffsets(index, resolved.start, resolved.end) : null
        range?.startContainer.parentElement?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        // Only a change of the active thread scrolls. A poll that refreshes the threads must not.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeThreadId])

    useEffect(() => {
        if (!selectable) {
            return
        }
        let frame = 0
        const readSelection = (): void => {
            const root = rootRef.current
            const container = containerRef.current
            if (!root || !container) {
                return
            }
            const selection = window.getSelection()
            const range = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null
            if (
                !range ||
                range.collapsed ||
                !root.contains(range.startContainer) ||
                !root.contains(range.endContainer)
            ) {
                if (logic.values.pendingAnchor?.kind === 'text') {
                    dismissPending()
                }
                return
            }
            const offsets = selectionOffsets(root, range)
            const anchor = createTextCommentAnchor(buildTextNodeIndex(root).text, offsets.start, offsets.end)
            if (!anchor) {
                return
            }
            // The box opens under the last line of the selection, where the pointer let go.
            const rects = Array.from(range.getClientRects()).filter((rect) => rect.width > 0)
            const end = rects.at(-1) ?? range.getBoundingClientRect()
            const box = container.getBoundingClientRect()
            const scaleX = box.width / container.offsetWidth || 1
            const scaleY = box.height / container.offsetHeight || 1
            const maxLeft = container.clientWidth - PENDING_COMMENT_WIDTH_PX - EDGE_MARGIN_PX
            setPendingAnchor(anchor, {
                left: Math.max(EDGE_MARGIN_PX, Math.min((end.left - box.left) / scaleX, maxLeft)),
                top: (end.bottom - box.top) / scaleY + 6,
            })
        }
        const onRelease = (event: Event): void => {
            const target = event.target
            if (target instanceof Element && target.closest('[data-pending-artifact-comment]')) {
                return
            }
            if (event instanceof KeyboardEvent && !event.shiftKey) {
                return
            }
            cancelAnimationFrame(frame)
            frame = requestAnimationFrame(readSelection)
        }
        document.addEventListener('pointerup', onRelease)
        document.addEventListener('keyup', onRelease)
        return () => {
            cancelAnimationFrame(frame)
            document.removeEventListener('pointerup', onRelease)
            document.removeEventListener('keyup', onRelease)
        }
    }, [logic, setPendingAnchor, dismissPending, selectable])

    const firstRectIndex = new Map<string, number>()
    rects.forEach((rect, index) => {
        if (!firstRectIndex.has(rect.id)) {
            firstRectIndex.set(rect.id, index)
        }
    })

    const activeEnd = rects.filter((rect) => rect.id === activeThreadId).at(-1)
    const pendingText = pendingAnchor?.kind === 'text' && !!pendingPosition
    const maxThreadLeft = (containerRef.current?.clientWidth ?? 0) - INLINE_THREAD_WIDTH_PX - EDGE_MARGIN_PX

    return (
        <div ref={containerRef} className="relative">
            <div ref={rootRef}>{children}</div>
            <div className="pointer-events-none absolute inset-0 z-10">
                {rects.map((rect, index) => (
                    <button
                        // A quote can wrap over several lines, so one thread can have several boxes.
                        key={`${rect.id}-${index}`}
                        type="button"
                        tabIndex={firstRectIndex.get(rect.id) === index ? 0 : -1}
                        aria-label={rect.label}
                        // The same yellow as PostHog Desktop in both themes, so a highlight reads on dark text too.
                        className={cn(
                            'pointer-events-auto absolute cursor-pointer rounded-xs',
                            rect.id === activeThreadId
                                ? 'border-b-2 border-warning bg-yellow-400/50'
                                : 'bg-yellow-400/30 hover:bg-yellow-400/45'
                        )}
                        // Positions come from measured text boxes, which utility classes cannot express.
                        style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
                        onClick={() => activateThread(rect.id)}
                        data-attr="task-artifact-comment-highlight"
                    />
                ))}
            </div>
            {activeEnd && !pendingText && (
                <ArtifactInlineThread
                    logicProps={logicProps}
                    style={{
                        left: Math.max(EDGE_MARGIN_PX, Math.min(activeEnd.left, maxThreadLeft)),
                        top: activeEnd.top + activeEnd.height + 6,
                    }}
                />
            )}
            {pendingAnchor?.kind === 'text' && pendingPosition && (
                <ArtifactPendingComment
                    logicProps={logicProps}
                    style={{ left: pendingPosition.left, top: pendingPosition.top }}
                />
            )}
        </div>
    )
}
