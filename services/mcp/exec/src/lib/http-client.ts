export interface HttpClientConfig {
    baseUrl: string
    apiKey: string
    userAgent?: string
}

export interface HttpRequest {
    method: string
    path: string
    query?: Record<string, unknown> | undefined
    body?: unknown
    headers?: Record<string, string>
}

/**
 * Thin fetch wrapper. Auth via Bearer token, optional query string, optional JSON body.
 * Throws an HttpError with status + body on non-2xx responses so the SnippetRunner
 * can classify the failure as `http`.
 */
export class HttpClient {
    private readonly baseUrl: string
    private readonly apiKey: string
    private readonly userAgent: string

    constructor(config: HttpClientConfig) {
        this.baseUrl = config.baseUrl.replace(/\/$/, '')
        this.apiKey = config.apiKey
        this.userAgent = config.userAgent ?? 'posthog-mcp-exec/0.1'
    }

    async request<T>(req: HttpRequest): Promise<T> {
        const url = new URL(this.baseUrl + req.path)
        if (req.query) {
            for (const [key, value] of Object.entries(req.query)) {
                if (value === undefined || value === null) {
                    continue
                }
                if (Array.isArray(value)) {
                    for (const v of value) {
                        url.searchParams.append(key, String(v))
                    }
                } else {
                    url.searchParams.append(key, String(value))
                }
            }
        }

        const headers: Record<string, string> = {
            Authorization: `Bearer ${this.apiKey}`,
            Accept: 'application/json',
            'User-Agent': this.userAgent,
            ...req.headers,
        }

        const init: RequestInit = {
            method: req.method,
            headers,
        }

        if (req.body !== undefined && req.method !== 'GET' && req.method !== 'HEAD') {
            headers['Content-Type'] = 'application/json'
            init.body = JSON.stringify(req.body)
        }

        const response = await fetch(url, init)
        const text = await response.text()
        const parsed = text ? this.tryParseJson(text) : undefined

        if (!response.ok) {
            throw new HttpError(response.status, response.statusText, parsed ?? text, url.toString())
        }

        return parsed as T
    }

    private tryParseJson(text: string): unknown {
        try {
            return JSON.parse(text)
        } catch {
            return text
        }
    }
}

export class HttpError extends Error {
    public readonly kind = 'http'

    constructor(
        public readonly status: number,
        public readonly statusText: string,
        public readonly body: unknown,
        public readonly url: string
    ) {
        super(`HTTP ${status} ${statusText} on ${url}`)
        this.name = 'HttpError'
    }
}
