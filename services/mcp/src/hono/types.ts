import type { Context } from 'hono'

import type { RedisLike } from './cache/RedisCache'

export type HonoCtx = Context

export type RedisWithPing = RedisLike & { ping?(): Promise<string> }
