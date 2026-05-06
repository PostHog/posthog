import { beforeEach, describe, expect, it, vi } from 'vitest'

const ApiClientCtor = vi.fn()

vi.mock('@/api/client', () => ({
    ApiClient: class {
        config: { apiToken: string; baseUrl: string }
        baseUrl: string
        constructor(config: any) {
            this.config = config
            this.baseUrl = config.baseUrl
            ApiClientCtor(config)
        }
    },
}))

const storagePutSpy = vi.fn()
const superSetNameSpy = vi.fn()
const superUpdatePropsSpy = vi.fn()

// Stand-in for the agents/mcp base class. Mirrors the two methods our overrides
// chain into via `super`:
//   - updateProps persists to storage and sets this.props (cold start / wake)
//   - setName is a noop here; partyserver's real implementation updates the
//     private #_props. Our subclass override handles the subclass-visible state.
vi.mock('agents/mcp', () => ({
    McpAgent: class {
        async setName(name: string, props?: unknown): Promise<void> {
            superSetNameSpy(name, props)
        }
        async updateProps(props: unknown): Promise<void> {
            superUpdatePropsSpy(props)
            await (this as any).ctx.storage.put('props', props ?? {})
            ;(this as any).props = props
        }
    },
}))

vi.mock('@modelcontextprotocol/sdk/server/mcp.js', () => ({
    McpServer: class {},
}))

vi.mock('@modelcontextprotocol/ext-apps/server', () => ({
    RESOURCE_URI_META_KEY: 'resource-uri',
}))

vi.mock('@shared/guidelines.md', () => ({
    default: '',
}))

import { MCP } from '@/mcp'

function buildMcp(initialToken: string): MCP {
    const mcp = Object.create(MCP.prototype) as MCP
    ;(mcp as any).props = {
        userHash: 'user-hash',
        apiToken: initialToken,
        clientUserAgent: 'test-agent',
    }
    ;(mcp as any).ctx = {
        storage: {
            put: async (key: string, value: unknown) => {
                storagePutSpy(key, value)
            },
        },
    }
    ;(mcp as any).getBaseUrl = async () => 'https://us.posthog.com'
    ;(mcp as any).resolveClientInfo = async () => {}
    return mcp
}

type TestProps = { userHash: string; apiToken: string; clientUserAgent: string }

function nextProps(apiToken: string): TestProps {
    return {
        userHash: 'user-hash',
        apiToken,
        clientUserAgent: 'test-agent',
    }
}

describe('MCP.api() lazy construction', () => {
    beforeEach(() => {
        ApiClientCtor.mockClear()
        storagePutSpy.mockClear()
    })

    it('constructs an ApiClient with the current token on first call', async () => {
        const mcp = buildMcp('token-A')
        const api = await mcp.api()

        expect(ApiClientCtor).toHaveBeenCalledTimes(1)
        expect(ApiClientCtor).toHaveBeenLastCalledWith(expect.objectContaining({ apiToken: 'token-A' }))
        expect(api.config.apiToken).toBe('token-A')
    })

    it('returns the cached instance on subsequent calls', async () => {
        const mcp = buildMcp('token-A')
        const first = await mcp.api()
        const second = await mcp.api()

        expect(ApiClientCtor).toHaveBeenCalledTimes(1)
        expect(second).toBe(first)
    })

    it('does NOT rotate the cached token when props.apiToken changes directly', async () => {
        // Token rotation lives in setName() / updateProps() now, not api().
        // Mutating this.props.apiToken directly must NOT cause api() to rewrite
        // the cached client's token: the rotation seam is the props-ingress path.
        const mcp = buildMcp('token-A')
        const first = await mcp.api()
        ;(mcp as any).props.apiToken = 'token-B'
        const second = await mcp.api()

        expect(second).toBe(first)
        expect(ApiClientCtor).toHaveBeenCalledTimes(1)
        expect(second.config.apiToken).toBe('token-A')
    })
})

describe('MCP.setName() token rotation (warm DO path)', () => {
    beforeEach(() => {
        ApiClientCtor.mockClear()
        storagePutSpy.mockClear()
        superSetNameSpy.mockClear()
        superUpdatePropsSpy.mockClear()
    })

    it('delegates to super.setName with the same arguments', async () => {
        const mcp = buildMcp('token-A')
        const props = nextProps('token-B')

        await (mcp as any).setName('streamable-http:session-1', props)

        expect(superSetNameSpy).toHaveBeenCalledTimes(1)
        expect(superSetNameSpy).toHaveBeenCalledWith('streamable-http:session-1', props)
    })

    it('rotates the cached ApiClient token in place on warm requests', async () => {
        const mcp = buildMcp('token-A')
        const api = await mcp.api()
        expect(api.config.apiToken).toBe('token-A')

        await (mcp as any).setName('streamable-http:session-1', nextProps('token-B'))

        // Same instance reference — context.api captured during init() still
        // points at the live ApiClient, so mutating in place propagates.
        expect(api.config.apiToken).toBe('token-B')
        expect(ApiClientCtor).toHaveBeenCalledTimes(1)
    })

    it('leaves this.props untouched (partyserver owns #_props)', async () => {
        const mcp = buildMcp('token-A')
        await mcp.api()

        await (mcp as any).setName('streamable-http:session-1', nextProps('token-B'))

        // setName only rotates the cached token. this.props stays as whatever
        // updateProps last wrote; partyserver's private #_props is what holds
        // the fresh per-request props.
        expect((mcp as any).props.apiToken).toBe('token-A')
    })

    it('does NOT persist to storage', async () => {
        // Storage writes are the cold-start / hibernation concern handled by
        // updateProps. setName must stay cheap — it fires on every request.
        const mcp = buildMcp('token-A')
        await mcp.api()

        await (mcp as any).setName('streamable-http:session-1', nextProps('token-B'))

        expect(storagePutSpy).not.toHaveBeenCalled()
    })

    it('is a no-op on the cached token when no ApiClient has been constructed', async () => {
        const mcp = buildMcp('token-A')

        await (mcp as any).setName('streamable-http:session-1', nextProps('token-B'))

        // Nothing to rotate — the next api() call will build fresh with
        // whatever requestProperties returns at that point.
        expect(ApiClientCtor).not.toHaveBeenCalled()
    })

    it('is a no-op when props is undefined', async () => {
        const mcp = buildMcp('token-A')
        const api = await mcp.api()

        await (mcp as any).setName('streamable-http:session-1', undefined)

        expect(api.config.apiToken).toBe('token-A')
    })

    it('is a no-op when props has no apiToken field', async () => {
        const mcp = buildMcp('token-A')
        const api = await mcp.api()

        await (mcp as any).setName('streamable-http:session-1', { userHash: 'user-hash' })

        expect(api.config.apiToken).toBe('token-A')
    })

    it('is a no-op when the incoming token matches the cached one', async () => {
        const mcp = buildMcp('token-A')
        const api = await mcp.api()
        const before = api.config.apiToken

        await (mcp as any).setName('streamable-http:session-1', nextProps('token-A'))

        expect(api.config.apiToken).toBe(before)
    })
})

describe('MCP.updateProps() token propagation (cold start / hibernation)', () => {
    beforeEach(() => {
        ApiClientCtor.mockClear()
        storagePutSpy.mockClear()
        superSetNameSpy.mockClear()
        superUpdatePropsSpy.mockClear()
    })

    it('persists the new props to storage via super.updateProps', async () => {
        const mcp = buildMcp('token-A')
        const props = nextProps('token-B')

        await (mcp as any).updateProps(props)

        expect(superUpdatePropsSpy).toHaveBeenCalledTimes(1)
        expect(superUpdatePropsSpy).toHaveBeenCalledWith(props)
        expect(storagePutSpy).toHaveBeenCalledTimes(1)
        expect(storagePutSpy).toHaveBeenCalledWith('props', props)
    })

    it('propagates the new token onto the cached ApiClient', async () => {
        const mcp = buildMcp('token-A')
        const api = await mcp.api()
        expect(api.config.apiToken).toBe('token-A')

        await (mcp as any).updateProps(nextProps('token-B'))

        expect(api.config.apiToken).toBe('token-B')
        expect(ApiClientCtor).toHaveBeenCalledTimes(1)
    })

    it('rotates the token synchronously, before awaiting storage', async () => {
        // The agents SDK fires updateProps without awaiting before dispatching
        // a fetch, so concurrent tool calls must see the new token on
        // context.api.config.apiToken *before* storage.put resolves.
        const mcp = buildMcp('token-A')
        const api = await mcp.api()

        const updatePromise = (mcp as any).updateProps(nextProps('token-B'))

        expect(api.config.apiToken).toBe('token-B')
        expect((mcp as any).props.apiToken).toBe('token-B')

        await updatePromise
        expect(storagePutSpy).toHaveBeenCalledTimes(1)
    })

    it('is a no-op on the ApiClient when none has been constructed yet', async () => {
        const mcp = buildMcp('token-A')

        await (mcp as any).updateProps(nextProps('token-B'))

        const api = await mcp.api()
        expect(ApiClientCtor).toHaveBeenCalledTimes(1)
        expect(api.config.apiToken).toBe('token-B')
    })

    it('leaves the cached ApiClient untouched when the token is unchanged', async () => {
        const mcp = buildMcp('token-A')
        const api = await mcp.api()

        await (mcp as any).updateProps(nextProps('token-A'))

        expect(api.config.apiToken).toBe('token-A')
        expect(ApiClientCtor).toHaveBeenCalledTimes(1)
    })

    it('tolerates missing props without throwing', async () => {
        const mcp = buildMcp('token-A')
        const api = await mcp.api()

        await expect((mcp as any).updateProps(undefined)).resolves.toBeUndefined()

        expect(api.config.apiToken).toBe('token-A')
    })

    it('tolerates props without an apiToken field', async () => {
        const mcp = buildMcp('token-A')
        const api = await mcp.api()

        await (mcp as any).updateProps({ userHash: 'user-hash' })

        expect(api.config.apiToken).toBe('token-A')
    })
})
