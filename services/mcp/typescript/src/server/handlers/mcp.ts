import type { Request, Response, NextFunction, RequestHandler } from 'express'

import { MCP_DOCS_URL } from '@/lib/constants'
import type { Metrics } from '../metrics'
import type { McpService } from '../services/mcp'

export function createMcpHandler(mcpService: McpService, metrics: Metrics): RequestHandler {
    return async (req: Request, res: Response, next: NextFunction): Promise<void> => {
        const startTime = Date.now()

        try {
            const token = req.headers.authorization?.split(' ')[1]

            if (!token) {
                metrics.incRequest(req.method, '401')
                res.status(401).json({
                    error: `No token provided. View the documentation: ${MCP_DOCS_URL}`,
                })
                return
            }

            if (!token.startsWith('phx_') && !token.startsWith('pha_')) {
                metrics.incRequest(req.method, '401')
                res.status(401).json({
                    error: `Invalid token format. View the documentation: ${MCP_DOCS_URL}`,
                })
                return
            }

            const url = new URL(req.url, `http://${req.headers.host}`)
            const sessionId = url.searchParams.get('sessionId') || undefined
            const featuresParam = url.searchParams.get('features')
            const features = featuresParam ? featuresParam.split(',').filter(Boolean) : undefined

            const handler = await mcpService.createHandler({
                apiToken: token,
                sessionId,
                features,
            })

            await handler(req, res)

            const durationSeconds = (Date.now() - startTime) / 1000
            metrics.observeDuration(req.method, durationSeconds)
            metrics.incRequest(req.method, String(res.statusCode))
        } catch (error) {
            next(error)
        }
    }
}
