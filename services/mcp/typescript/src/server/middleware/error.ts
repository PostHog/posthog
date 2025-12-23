import type { Request, Response, NextFunction, ErrorRequestHandler } from 'express'

import type { Metrics } from '../metrics'

export function createErrorMiddleware(metrics: Metrics): ErrorRequestHandler {
    return (err: Error, req: Request, res: Response, _next: NextFunction): void => {
        console.error('Server error:', err)
        metrics.incRequest(req.method, '500')
        res.status(500).json({ error: 'Internal server error' })
    }
}
