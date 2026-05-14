import { timingSafeEqual } from 'node:crypto'
import { NextFunction, Request, Response } from 'ultimate-express'

export interface InternalAuthOptions {
    /** Shared key the proxy/Django supplies via `x-internal-key`. */
    sharedKey: string | undefined
}

/**
 * Gate `/internal/*` routes behind a static shared key. When the key isn't configured
 * we refuse all traffic — a janitor without a key is a foot-gun in production.
 *
 * mTLS at the mesh level (when we get there) is the longer-term plan; this header
 * check is a defense-in-depth layer that doesn't need infra cooperation.
 */
export function requireInternalKey(options: InternalAuthOptions) {
    return (req: Request, res: Response, next: NextFunction): void => {
        if (!options.sharedKey) {
            res.status(500).json({ error: 'AGENT_INTERNAL_API_SHARED_KEY not configured' })
            return
        }
        const presented = req.header('x-internal-key') ?? ''
        if (!constantTimeEqual(presented, options.sharedKey)) {
            res.status(401).json({ error: 'invalid internal key' })
            return
        }
        next()
    }
}

function constantTimeEqual(a: string, b: string): boolean {
    const ab = Buffer.from(a, 'utf8')
    const bb = Buffer.from(b, 'utf8')
    if (ab.length !== bb.length) {
        return false
    }
    return timingSafeEqual(ab, bb)
}
