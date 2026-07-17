// Hono application-level types for the agent-proxy.
//
// HonoVariables is the context variables map wired into the Hono app. Route
// handlers use HonoCtx to get typed access to c.get('requestLogger') without
// casts.

import type { Context } from 'hono'

import type { RequestLogger } from '../lib/logging.js'

export type HonoVariables = { requestLogger: RequestLogger }
export type HonoCtx = Context<{ Variables: HonoVariables }>

// Lifecycle flag shared between app factory, public-routes, and shutdown handler.
export interface Lifecycle {
    shuttingDown: boolean
}
