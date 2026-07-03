// Domain types, error classes and discriminated unions for the agent-proxy.
// Shapes defined here must stay compatible with the Python counterparts in
// products/tasks/backend/stream/redis_stream.py and
// products/tasks/backend/proxy/event_ingest.py — both sides share the same
// Redis stream and HTTP contracts.

import type { Redis } from 'ioredis'

// ---------------------------------------------------------------------------
// Error classes
// ---------------------------------------------------------------------------

export class TaskRunStreamError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'TaskRunStreamError'
    }
}

export class TaskRunStreamSequenceGap extends Error {
    constructor(
        public readonly expectedSequence: number,
        public readonly receivedSequence: number,
        public readonly lastAcceptedSeq: number
    ) {
        super(`Expected sequence ${expectedSequence}, got ${receivedSequence}`)
        this.name = 'TaskRunStreamSequenceGap'
    }
}

export class TaskRunStreamCompletionSequenceMismatch extends Error {
    constructor(
        public readonly finalSequence: number,
        public readonly lastAcceptedSeq: number
    ) {
        super(`Cannot complete stream at sequence ${finalSequence}; last accepted sequence is ${lastAcceptedSeq}`)
        this.name = 'TaskRunStreamCompletionSequenceMismatch'
    }
}

export class TaskRunStreamAlreadyCompleted extends Error {
    constructor(public readonly lastAcceptedSeq: number) {
        super('Task run stream is already complete')
        this.name = 'TaskRunStreamAlreadyCompleted'
    }
}

export class EventIngestBadRequest extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'EventIngestBadRequest'
    }
}

export class EventIngestPayloadTooLarge extends Error {
    constructor(
        message: string,
        public lastAcceptedSeq: number = 0
    ) {
        super(message)
        this.name = 'EventIngestPayloadTooLarge'
    }
}

export class ClientDisconnected extends Error {
    accepted = 0
    duplicate = 0
    lastAcceptedSeq = 0

    constructor() {
        super('Client disconnected during event ingest')
        this.name = 'ClientDisconnected'
    }
}

// ---------------------------------------------------------------------------
// Redis stream types
// ---------------------------------------------------------------------------

// Returned by detectResumeGap when the client's Last-Event-ID has been trimmed.
// S3 hydration is out of scope; callers log and continue from oldestAvailableId.
export interface ResumeGap {
    requestedId: string
    oldestAvailableId: string
}

// ---------------------------------------------------------------------------
// JWT claim types
// ---------------------------------------------------------------------------

// Claims extracted from a posthog:stream_read JWT (GET /v1/runs/:run/stream leg)
export interface StreamReadTokenPayload {
    runId: string
    taskId: string
    teamId: number
}

// Claims extracted from a posthog:sandbox_event_ingest JWT (POST /v1/runs/:run/ingest leg)
export interface SandboxEventIngestTokenPayload {
    runId: string
    taskId: string
    teamId: number
}

// ---------------------------------------------------------------------------
// SSE stream connection outcome (matches Python StreamConnectionOutcome values)
// ---------------------------------------------------------------------------

export type StreamConnectionOutcome = 'completed' | 'stream_error' | 'unavailable' | 'client_disconnect'

// ---------------------------------------------------------------------------
// Ingest HTTP response shape (200 OK body)
// ---------------------------------------------------------------------------

export interface EventIngestResult {
    accepted: number
    duplicate: number
    last_accepted_seq: number
}

// ---------------------------------------------------------------------------
// Parsed NDJSON line discriminated union
// ---------------------------------------------------------------------------

export interface IngestEventLine {
    kind: 'event'
    seq: number
    event: Record<string, unknown>
}

export interface IngestCompleteLine {
    kind: 'complete'
    finalSeq: number
}

export type IngestLine = IngestEventLine | IngestCompleteLine

// ---------------------------------------------------------------------------
// Side-effect callback kind (matches Python callback contract in docs/DESIGN.md)
// ---------------------------------------------------------------------------

export type SideEffectKind = 'heartbeat' | 'awaiting_input'

// ---------------------------------------------------------------------------
// TaskRunRedisStream method interface
// ---------------------------------------------------------------------------

// Async generator element: either a [streamId, event] tuple or null (keepalive signal).
export type StreamEntry = [string, Record<string, unknown>]
export type StreamEntryOrKeepalive = StreamEntry | null

export interface ReadStreamEntriesOptions {
    startId?: string
    blockMs?: number
    count?: number
    keepaliveIntervalMs?: number | null
    // When provided, this connection is used for the blocking XREAD call instead
    // of the class-level shared client — isolates blocking reads from ingest writes.
    blockingRedis?: Redis
}
