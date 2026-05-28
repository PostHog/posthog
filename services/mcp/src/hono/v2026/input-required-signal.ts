/**
 * Internal control-flow signal thrown by `Context.requestInput` when the
 * handler needs to surface a new input request.
 *
 * The dispatcher catches it, encodes the cumulative answers into a fresh
 * `requestState`, and returns an `InputRequiredResult` to the client.
 *
 * Not exposed to tool authors — the universal seam is `context.requestInput`,
 * which throws this internally and the dispatcher handles it. Tool code
 * never sees a `throw` happen at the `await` site.
 */

import type { ElicitRequestFormParams } from '@modelcontextprotocol/sdk/types.js'

export class InputRequiredSignal extends Error {
    constructor(
        readonly key: string,
        readonly elicitParams: ElicitRequestFormParams
    ) {
        super(`requestInput("${key}") needs a response — surfaced as InputRequiredResult`)
        this.name = 'InputRequiredSignal'
    }
}

export function isInputRequiredSignal(value: unknown): value is InputRequiredSignal {
    return value instanceof InputRequiredSignal
}
