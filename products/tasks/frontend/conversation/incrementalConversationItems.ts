import type { AcpMessage } from './acp-types'
import {
    type BuildConversationOptions,
    type BuildResult,
    buildConversationItems,
    type ConversationItem,
    createItemBuilder,
    type ItemBuilder,
    type LastTurnInfo,
    markThoughtCompletion,
    processEvent,
    readLastTurnInfo,
    type TurnContext,
} from './buildConversationItems'

/**
 * Incremental front end for `buildConversationItems`.
 *
 * A full rebuild re-parses every event on every streamed token — O(n) per
 * token, O(n^2) per turn. This processes each event exactly once into a
 * persistent builder and, on every call, freezes completed turns (their item
 * objects keep identity, so memoized rows skip re-render) while re-deriving
 * only the active turn. Per call the cost is proportional to the active turn,
 * not the whole thread.
 *
 * Output is content-equivalent to `buildConversationItems` for every prefix of
 * events — see incrementalConversationItems.test.ts. It falls back to a full
 * rebuild whenever the append-only fast path can't faithfully represent the
 * state (idle, non-append event change, options change, or a progress card in
 * an already-frozen turn being mutated).
 */
export function createIncrementalConversationBuilder(): {
    update: (events: AcpMessage[], isPromptPending: boolean | null, options?: BuildConversationOptions) => BuildResult
    reset: () => void
} {
    let b: ItemBuilder | null = null
    let processedCount = 0
    let firstEventRef: AcpMessage | null = null
    let boundaryEventRef: AcpMessage | null = null
    let showDebugLogs: boolean | undefined

    function reset(): void {
        b = null
        processedCount = 0
        firstEventRef = null
        boundaryEventRef = null
    }

    function update(
        events: AcpMessage[],
        isPromptPending: boolean | null,
        options?: BuildConversationOptions
    ): BuildResult {
        const debug = options?.showDebugLogs

        // Idle (not streaming): cheap to rebuild, and it sidesteps the speculative
        // end-of-stream completions that only `buildConversationItems` resolves.
        if (isPromptPending === false) {
            reset()
            return buildConversationItems(events, isPromptPending, options)
        }

        // The fast path is valid only when this call appends to the exact prefix we
        // already processed (events is append-only during streaming, immer hands us
        // a new array each push but keeps element identity).
        const canAppend =
            b !== null &&
            debug === showDebugLogs &&
            events.length >= processedCount &&
            (processedCount === 0 || events[0] === firstEventRef) &&
            (processedCount === 0 || events[processedCount - 1] === boundaryEventRef)

        if (!canAppend) {
            b = createItemBuilder()
            processedCount = 0
            showDebugLogs = debug
        }

        const builder = b as ItemBuilder
        builder.lowestTouchedProgressIndex = Number.POSITIVE_INFINITY
        for (let i = processedCount; i < events.length; i++) {
            processEvent(builder, events[i], options)
        }
        processedCount = events.length
        firstEventRef = events[0] ?? null
        boundaryEventRef = events[processedCount - 1] ?? null

        const turn = builder.currentTurn
        const activeStart = turn && !turn.isComplete ? builder.currentTurnStartIndex : builder.items.length

        // A progress card living in the frozen region was mutated by this batch —
        // an event reached back across a turn boundary. The append-only view can't
        // show that, so rebuild fully this frame (the persistent builder stays
        // valid for the next one).
        if (builder.lowestTouchedProgressIndex < activeStart) {
            return buildConversationItems(events, isPromptPending, options)
        }

        // `buildConversationItems` always marks a trailing implicit turn complete.
        // Replicate that on the live turn's context so thought-completion matches;
        // it's safe to persist (a later real completion still flows through
        // `completePromptTurn`, which gates on `isComplete`, left untouched here).
        if (turn && turn.promptId === -1) {
            turn.context.turnComplete = true
        }

        markThoughtCompletion(builder.items)

        return {
            items: assembleItems(builder, activeStart),
            lastTurnInfo: readLastTurnInfoForOutput(builder),
            isCompacting: builder.isCompacting,
        }
    }

    return { update, reset }
}

function assembleItems(b: ItemBuilder, activeStart: number): ConversationItem[] {
    // Completed turns: reuse the builder's own objects. They aren't rebuilt
    // across calls, so their identity is stable and memoized rows skip work.
    const out = b.items.slice(0, activeStart)
    if (activeStart >= b.items.length) {
        return out
    }

    const turn = b.currentTurn
    // The active turn streams: clone its rows onto a fresh shared context each
    // call so their memoized views re-render and read the latest tool/child
    // state — matching the all-new-objects behavior a full rebuild gives the
    // live turn. Non-update rows (the user message, git actions) never change,
    // so pass them through by reference.
    const activeContext: TurnContext | null = turn
        ? {
              toolCalls: turn.context.toolCalls,
              childItems: turn.context.childItems,
              turnCancelled: turn.context.turnCancelled,
              turnComplete: turn.context.turnComplete,
          }
        : null

    for (let i = activeStart; i < b.items.length; i++) {
        const item = b.items[i]
        if (item.type === 'session_update' && activeContext) {
            out.push({ ...item, turnContext: activeContext })
        } else {
            out.push(item)
        }
    }
    return out
}

function readLastTurnInfoForOutput(b: ItemBuilder): LastTurnInfo | null {
    const info = readLastTurnInfo(b)
    if (!info) {
        return null
    }
    // A trailing implicit turn reports complete (no prompt response will arrive
    // to flip it), mirroring `buildConversationItems`' finalization.
    if (b.currentTurn?.promptId === -1) {
        return { ...info, isComplete: true }
    }
    return info
}
