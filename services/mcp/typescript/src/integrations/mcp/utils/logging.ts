// Wide log class for accumulating request data and emitting a single log at the end
export class RequestLogger {
    private data: Record<string, unknown> = {}
    private startTime = Date.now()

    constructor(requestId?: string) {
        this.data.requestId = requestId ?? crypto.randomUUID().slice(0, 8)
    }

    extend(data: Record<string, unknown>): void {
        Object.assign(this.data, data)
    }

    emit(status: number): void {
        this.data.status = status
        this.data.durationMs = Date.now() - this.startTime
        console.log('[MCP]', JSON.stringify(this.data))
    }
}

type FetchHandler<Props> = (
    request: Request,
    env: Env,
    ctx: ExecutionContext<Props>,
    log: RequestLogger
) => Promise<Response>

// Middleware that wraps a handler with automatic wide logging
export function withLogging<Props>(handler: FetchHandler<Props>) {
    return async (request: Request, env: Env, ctx: ExecutionContext<Props>) => {
        const log = new RequestLogger()

        const url = new URL(request.url)
        const headers: Record<string, string> = {}
        request.headers.forEach((value, key) => {
            headers[key] = key.toLowerCase() === 'authorization' && value.length > 20 ? value.slice(0, 20) + '...' : value
        })

        log.extend({
            method: request.method,
            pathname: url.pathname,
            search: url.search,
            headers,
        })

        if (request.method === 'POST') {
            log.extend({ body: await request.clone().text() })
        }

        try {
            const response = await handler(request, env, ctx, log)
            log.emit(response.status)
            return response
        } catch (error) {
            log.extend({ error: error instanceof Error ? error.message : String(error) })
            log.emit(500)
            throw error
        }
    }
}
