import type { Request, Response, RequestHandler } from 'express'
import type { Redis } from 'ioredis'

export function createHealthHandler(): RequestHandler {
    return (_req: Request, res: Response): void => {
        res.send('OK')
    }
}

export function createReadyHandler(redis?: Redis): RequestHandler {
    return async (_req: Request, res: Response): Promise<void> => {
        if (redis) {
            try {
                await redis.ping()
            } catch {
                res.status(503).send('Redis not ready')
                return
            }
        }
        res.send('OK')
    }
}
