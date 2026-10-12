import type { CommentApi } from 'products/platform_features/frontend/generated/api.schemas'

import type { ArtifactPreviewKind, RunArtifact } from './taskRunArtifacts'

// Artifact comments are ordinary PostHog comments with scope "task_artifact" and the artifact version id as
// item_id. PostHog Desktop writes the same rows with the same item_context shape, so both apps show each
// other's threads, pins and highlights.

// pinned: comment scope for task artifacts, shared with PostHog Desktop and the comments API
export const ARTIFACT_COMMENT_SCOPE = 'task_artifact'

// The same limits Desktop uses, so an anchor written here also passes Desktop's schema.
const CONTEXT_LENGTH = 32
const MAX_QUOTE_LENGTH = 10_000
// The side of a new pin's region, as a share of the image width and height.
const PIN_REGION_SIZE = 0.035

export interface TextCommentAnchor {
    kind: 'text'
    quote: string
    prefix: string
    suffix: string
    start: number
    end: number
}

/** A box on an image. Every value is a share of the image size, from 0 to 1. */
export interface RegionCommentAnchor {
    kind: 'region'
    x: number
    y: number
    width: number
    height: number
}

export interface DocumentCommentAnchor {
    kind: 'document'
}

export type ArtifactCommentAnchor = TextCommentAnchor | RegionCommentAnchor | DocumentCommentAnchor

/** The anchor names in analytics. They match the words the UI uses. */
export type ArtifactCommentAnchorKind = 'document' | 'image' | 'selection'

export type ThreadState = 'resolved' | 'open'

export interface ArtifactCommentContext {
    anchor: ArtifactCommentAnchor | null
    threadState: ThreadState | null
}

export interface ArtifactCommentThread {
    root: CommentApi
    /** Replies people wrote, oldest first. Resolve and reopen records stay out. */
    replies: CommentApi[]
    resolved: boolean
    anchor: ArtifactCommentAnchor | null
    /** Set on a region thread: its number among the image's pins, from 1, in the order people placed them. */
    pinNumber: number | null
}

/** Where a text range sits in a document. `status` is `reanchored` when the text moved since the comment. */
export interface ResolvedTextAnchor {
    start: number
    end: number
    status: 'exact' | 'reanchored'
}

export function anchorKindLabel(anchor: ArtifactCommentAnchor | null): ArtifactCommentAnchorKind {
    return anchor?.kind === 'region' ? 'image' : anchor?.kind === 'text' ? 'selection' : 'document'
}

/** The accessible name of a thread: the text or the pin it is about. */
export function threadAnchorLabel(thread: ArtifactCommentThread): string {
    if (thread.anchor?.kind === 'text') {
        return `Comments on "${thread.anchor.quote}"`
    }
    return thread.pinNumber ? `Comments on pin ${thread.pinNumber}` : 'Comments on this file'
}

/** Comments need a stable artifact id the server can find on the task. Cited objects and living documents have none. */
export function isCommentableArtifact(artifact: RunArtifact | null): artifact is RunArtifact & { id: string } {
    return !!artifact?.id && artifact.type !== 'reference' && !artifact.living
}

/** Kinds where a person can select text in the rendered view and comment on it. */
export function supportsSelectionComments(kind: ArtifactPreviewKind | null): boolean {
    return kind === 'markdown' || kind === 'text'
}

function isShare(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
}

function readAnchor(value: unknown): ArtifactCommentAnchor | null {
    if (!value || typeof value !== 'object') {
        return null
    }
    const anchor = value as Record<string, unknown>
    if (anchor.kind === 'document') {
        return { kind: 'document' }
    }
    if (anchor.kind === 'region') {
        const { x, y, width, height } = anchor
        return isShare(x) && isShare(y) && isShare(width) && isShare(height)
            ? { kind: 'region', x, y, width, height }
            : null
    }
    if (anchor.kind === 'text') {
        const { quote, prefix, suffix, start, end } = anchor
        if (
            typeof quote !== 'string' ||
            !quote ||
            typeof prefix !== 'string' ||
            typeof suffix !== 'string' ||
            !Number.isInteger(start) ||
            !Number.isInteger(end) ||
            (start as number) < 0 ||
            (end as number) <= (start as number)
        ) {
            return null
        }
        return { kind: 'text', quote, prefix, suffix, start: start as number, end: end as number }
    }
    return null
}

/** The generated client types `item_context` as unknown, so each field is checked before use. */
export function readArtifactCommentContext(comment: Pick<CommentApi, 'item_context'>): ArtifactCommentContext {
    const context =
        comment.item_context && typeof comment.item_context === 'object'
            ? (comment.item_context as Record<string, unknown>)
            : {}
    const threadState =
        context.threadState === 'resolved' || context.threadState === 'open' ? context.threadState : null
    return { anchor: readAnchor(context.anchor), threadState }
}

function bySentAt(a: CommentApi, b: CommentApi): number {
    return a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id)
}

/** Groups a flat comment list into threads, oldest root first. */
export function buildArtifactCommentThreads(comments: readonly CommentApi[]): ArtifactCommentThread[] {
    const roots: CommentApi[] = []
    const repliesByRoot = new Map<string, CommentApi[]>()
    for (const comment of comments) {
        if (comment.deleted) {
            continue
        }
        if (!comment.source_comment) {
            roots.push(comment)
            continue
        }
        const replies = repliesByRoot.get(comment.source_comment) ?? []
        replies.push(comment)
        repliesByRoot.set(comment.source_comment, replies)
    }
    let pins = 0
    return roots.sort(bySentAt).map((root) => {
        const all = (repliesByRoot.get(root.id) ?? []).sort(bySentAt)
        // The newest resolve or reopen record wins. A thread without one follows the root's completion.
        const latestState = all
            .map((reply) => readArtifactCommentContext(reply).threadState)
            .filter((state): state is ThreadState => state !== null)
            .at(-1)
        const anchor = readArtifactCommentContext(root).anchor
        return {
            root,
            replies: all.filter((reply) => readArtifactCommentContext(reply).threadState === null),
            resolved: latestState ? latestState === 'resolved' : !!root.completed_at,
            anchor,
            pinNumber: anchor?.kind === 'region' ? ++pins : null,
        }
    })
}

/** The anchor for a text range of `text`, or null when the range holds no visible characters. */
export function createTextCommentAnchor(text: string, start: number, end: number): TextCommentAnchor | null {
    const safeStart = Math.max(0, Math.min(start, text.length))
    const safeEnd = Math.max(safeStart, Math.min(end, text.length))
    const quote = text.slice(safeStart, safeEnd)
    if (!quote.trim() || quote.length > MAX_QUOTE_LENGTH) {
        return null
    }
    return {
        kind: 'text',
        quote,
        prefix: text.slice(Math.max(0, safeStart - CONTEXT_LENGTH), safeStart),
        suffix: text.slice(safeEnd, safeEnd + CONTEXT_LENGTH),
        start: safeStart,
        end: safeEnd,
    }
}

/**
 * Finds a stored quote in `text` without a guess. The stored offsets are checked first. Desktop renders
 * markdown with a different component, so its offsets can be off here, and the quote is searched for then.
 * The prefix and suffix pick between repeats of the quote. A tie returns null, so a highlight never lands
 * on the wrong words.
 */
export function resolveTextCommentAnchor(text: string, anchor: TextCommentAnchor): ResolvedTextAnchor | null {
    if (text.slice(anchor.start, anchor.end) === anchor.quote) {
        return { start: anchor.start, end: anchor.end, status: 'exact' }
    }
    const candidates: number[] = []
    // Matches do not overlap, the same as Desktop, so both apps pick the same repeat of a quote.
    for (
        let match = text.indexOf(anchor.quote);
        match >= 0;
        match = text.indexOf(anchor.quote, match + anchor.quote.length)
    ) {
        candidates.push(match)
    }
    if (candidates.length === 0) {
        return null
    }
    const ranked = candidates
        .map((start) => {
            const end = start + anchor.quote.length
            let score = 0
            if (anchor.prefix && text.slice(Math.max(0, start - anchor.prefix.length), start) === anchor.prefix) {
                score += 2
            }
            if (anchor.suffix && text.slice(end, end + anchor.suffix.length) === anchor.suffix) {
                score += 2
            }
            return { start, score }
        })
        .sort((a, b) => b.score - a.score)
    if (ranked.length > 1 && (ranked[0].score === 0 || ranked[0].score === ranked[1].score)) {
        return null
    }
    return { start: ranked[0].start, end: ranked[0].start + anchor.quote.length, status: 'reanchored' }
}

/** A pin region centered on a click, as shares of the image size. The region stays inside the image. */
export function regionAnchorAt(x: number, y: number): RegionCommentAnchor {
    const clamp = (value: number): number => Math.max(0, Math.min(1 - PIN_REGION_SIZE, value - PIN_REGION_SIZE / 2))
    return { kind: 'region', x: clamp(x), y: clamp(y), width: PIN_REGION_SIZE, height: PIN_REGION_SIZE }
}
