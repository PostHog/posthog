import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import type { observationProgressLogicType } from './observationProgressLogicType'

export interface ObservationFrameProgress {
    frame: number
    estimatedTotalFrames: number
}

export interface ObservationRasterizerProgress {
    frame_progress: ObservationFrameProgress | null
}

/** Live progress payload from the `observation-progress` SSE event (mirrors backend ObservationProgress). */
export interface ObservationProgress {
    phase: string
    step: number
    total_steps: number
    rasterizer: ObservationRasterizerProgress | null
}

export interface ObservationProgressLogicProps {
    observationId: string
    /** Lets the dock list refresh on completion; optional since the details page has no dock. */
    sessionId?: string
}

interface StreamHandlers {
    setProgress: (progress: ObservationProgress) => void
    streamCompleted: () => void
    setStreamError: (error: string) => void
}

/** Parse one SSE block (`event: <label>\ndata: <json>`) from our progress endpoint and dispatch it. */
function dispatchSseBlock(block: string, handlers: StreamHandlers): void {
    let event = ''
    const dataLines: string[] = []
    for (const line of block.split('\n')) {
        if (line.startsWith('event:')) {
            event = line.slice('event:'.length).trim()
        } else if (line.startsWith('data:')) {
            dataLines.push(line.slice('data:'.length).replace(/^ /, ''))
        }
    }
    const data = dataLines.join('\n')
    if (event === 'observation-progress') {
        try {
            handlers.setProgress(JSON.parse(data))
        } catch {
            // Drop an unparseable tick; the next one refreshes the bar.
        }
    } else if (event === 'observation-complete') {
        handlers.streamCompleted()
    } else if (event === 'observation-error') {
        handlers.setStreamError(data)
    }
}

async function consumeProgressStream(
    teamId: number,
    observationId: string,
    signal: AbortSignal,
    handlers: StreamHandlers
): Promise<void> {
    // Plain GET so read-only users can stream too (api.createResponse POSTs, which is blocked for them).
    const response = await fetch(`/api/projects/${teamId}/vision/observations/${observationId}/progress/`, {
        method: 'GET',
        headers: { Accept: 'text/event-stream' },
        credentials: 'same-origin',
        signal,
    })
    if (!response.ok || !response.body) {
        return
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
        const { done, value } = await reader.read()
        if (done) {
            break
        }
        buffer += decoder.decode(value, { stream: true })
        let boundary = buffer.indexOf('\n\n')
        while (boundary !== -1) {
            dispatchSseBlock(buffer.slice(0, boundary), handlers)
            buffer = buffer.slice(boundary + 2)
            boundary = buffer.indexOf('\n\n')
        }
    }
}

/**
 * Streams live progress for one in-flight observation over SSE. Keyed by observation id, so the dock card and the
 * details page share a single stream. The stream self-terminates once the observation settles.
 */
export const observationProgressLogic = kea<observationProgressLogicType>([
    path(['products', 'replay_vision', 'frontend', 'observations', 'observationProgressLogic']),
    props({} as ObservationProgressLogicProps),
    key((props) => props.observationId),

    actions({
        setProgress: (progress: ObservationProgress) => ({ progress }),
        streamCompleted: true,
        setStreamError: (error: string) => ({ error }),
    }),

    reducers({
        progress: [
            null as ObservationProgress | null,
            {
                setProgress: (_, { progress }) => progress,
            },
        ],
        streamError: [
            null as string | null,
            {
                setStreamError: (_, { error }) => error,
            },
        ],
    }),

    listeners(({ props }) => ({
        streamCompleted: () => {
            // Refresh the dock list so the finished card swaps its progress bar for the result immediately,
            // instead of lingering until the next poll. No-op where the dock isn't mounted (e.g. details page).
            if (props.sessionId) {
                observationsDockLogic.findMounted({ sessionId: props.sessionId })?.actions.loadObservations()
            }
        },
    })),

    afterMount(({ props, actions, cache }) => {
        const teamId = teamLogic.values.currentTeamId
        if (!teamId) {
            return
        }
        // Disposable so the fetch is aborted on unmount and paused while the tab is hidden.
        cache.disposables.add(() => {
            const controller = new AbortController()
            void consumeProgressStream(teamId, props.observationId, controller.signal, actions).catch(() => {
                // Network/abort errors are non-fatal — the bar falls back to its time-based animation.
            })
            return () => controller.abort()
        }, 'progressStream')
    }),
])
