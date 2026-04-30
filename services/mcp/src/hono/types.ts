import type { Context } from 'hono'

import type { RedisLike } from './cache/RedisCache'

export type HonoEnv = { Variables: { redis: RedisLike } }
export type HonoCtx = Context<HonoEnv>

/** Convenience alias: a Redis client that may also expose a `ping` for `/readyz`. */
export type RedisWithPing = RedisLike & { ping?(): Promise<string> }
