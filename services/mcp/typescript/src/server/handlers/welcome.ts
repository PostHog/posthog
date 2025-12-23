import type { Request, Response, RequestHandler } from 'express'

import { MCP_DOCS_URL } from '@/lib/constants'

export function createWelcomeHandler(): RequestHandler {
    return (_req: Request, res: Response): void => {
        res.set('Content-Type', 'text/html')
        res.send(
            `<p>Welcome to the PostHog MCP Server. For setup and usage instructions, see: <a href="${MCP_DOCS_URL}">${MCP_DOCS_URL}</a></p>`
        )
    }
}
