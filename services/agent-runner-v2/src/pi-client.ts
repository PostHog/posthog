/**
 * pi.dev wire interface. The runner depends on this shape, not on a vendor
 * SDK. Two impls below: HttpPiClient (prod, hits pi.dev) and MockPiClient
 * (tests, returns canned responses).
 */

export interface PiInvokeRequest {
    model: string
    system: string
    tools: PiToolDeclaration[]
    messages: PiMessage[]
    /** Maximum tokens the model may emit. */
    max_tokens?: number
}

export interface PiToolDeclaration {
    name: string
    description: string
    input_schema: Record<string, unknown>
}

export type PiMessage =
    | { role: 'user'; content: string | PiUserContentBlock[] }
    | { role: 'assistant'; content: PiAssistantContentBlock[] }

export type PiUserContentBlock =
    | { type: 'text'; text: string }
    | { type: 'tool_result'; tool_use_id: string; content: string; is_error?: boolean }

export type PiAssistantContentBlock =
    | { type: 'text'; text: string }
    | { type: 'tool_use'; id: string; name: string; input: unknown }

export interface PiInvokeResponse {
    /** "end_turn" → assistant finished cleanly; "tool_use" → it called tools; "max_tokens" → cut off. */
    stop_reason: 'end_turn' | 'tool_use' | 'max_tokens' | 'error'
    content: PiAssistantContentBlock[]
    usage: { input_tokens: number; output_tokens: number }
}

export interface PiClient {
    invoke(req: PiInvokeRequest): Promise<PiInvokeResponse>
}

/* -------------------------------------------------------------------------- */

export class HttpPiClient implements PiClient {
    private readonly baseUrl: string
    private readonly apiKey: string

    constructor(opts: { baseUrl?: string; apiKey: string }) {
        this.baseUrl = opts.baseUrl ?? 'https://api.pi.dev'
        this.apiKey = opts.apiKey
    }

    async invoke(req: PiInvokeRequest): Promise<PiInvokeResponse> {
        const res = await fetch(`${this.baseUrl}/v1/invoke`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${this.apiKey}`,
            },
            body: JSON.stringify(req),
        })
        if (!res.ok) {
            throw new Error(`pi.dev HTTP ${res.status}: ${await res.text()}`)
        }
        return (await res.json()) as PiInvokeResponse
    }
}

/* -------------------------------------------------------------------------- */

export type MockResponder = (req: PiInvokeRequest) => PiInvokeResponse | Promise<PiInvokeResponse>

export class MockPiClient implements PiClient {
    private readonly responses: MockResponder[]
    public readonly calls: PiInvokeRequest[] = []
    private idx = 0

    constructor(responses: Array<PiInvokeResponse | MockResponder>) {
        this.responses = responses.map((r) => (typeof r === 'function' ? r : () => r))
    }

    async invoke(req: PiInvokeRequest): Promise<PiInvokeResponse> {
        this.calls.push(req)
        if (this.idx >= this.responses.length) {
            throw new Error(`MockPiClient out of responses (idx=${this.idx})`)
        }
        const responder = this.responses[this.idx++]
        return responder(req)
    }
}

/** Helper: build a simple assistant turn from text content. */
export function endTurn(text: string): PiInvokeResponse {
    return {
        stop_reason: 'end_turn',
        content: [{ type: 'text', text }],
        usage: { input_tokens: 0, output_tokens: 0 },
    }
}

/** Helper: build a tool-use turn. */
export function toolUseTurn(blocks: PiAssistantContentBlock[]): PiInvokeResponse {
    return {
        stop_reason: 'tool_use',
        content: blocks,
        usage: { input_tokens: 0, output_tokens: 0 },
    }
}
