import { strToU8, zipSync } from 'fflate'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockExecSkillsEnabled, mockGetCatalog, mockResolveState } = vi.hoisted(() => ({
    mockExecSkillsEnabled: vi.fn(),
    mockResolveState: vi.fn(),
    mockGetCatalog: vi.fn(),
}))

vi.mock('@/hono/skill-catalog-service', () => ({
    SkillCatalogService: vi.fn().mockImplementation(function () {
        return { getCatalog: mockGetCatalog }
    }),
}))

vi.mock('@/hono/analytics', () => ({ trackInitEvent: vi.fn() }))

vi.mock('@/hono/instructions', () => ({
    InstructionsBuilder: vi.fn().mockImplementation(function () {
        return { build: vi.fn(() => ''), execSkillsEnabled: mockExecSkillsEnabled }
    }),
}))

vi.mock('@/hono/request-state-resolver', () => ({
    RequestStateResolver: vi.fn().mockImplementation(function () {
        return { resolve: mockResolveState }
    }),
}))

vi.mock('@/hono/resource-catalog', () => ({
    ResourceCatalog: vi.fn().mockImplementation(function () {
        return {
            readResource: vi.fn(async () => ({ contents: [] })),
            revalidateContextMillResources: vi.fn(async () => {}),
        }
    }),
}))

import { ErrorCode, LATEST_PROTOCOL_VERSION } from '@modelcontextprotocol/sdk/types.js'

import type { RedisLike } from '@/hono/cache/RedisCache'
import { McpDispatcher } from '@/hono/dispatcher'
import type { RequestProperties } from '@/lib/request-properties'
import { SkillCatalog } from '@/skills/skill-catalog'

const SKILL_URI = 'skill://funnels/SKILL.md'
const SKILL_MD = '---\nname: funnels\ndescription: Analyze conversion funnels.\n---\n\n# Funnels\n'

function makeProps(): RequestProperties {
    return {
        apiToken: 'phx_test',
        mcpClientName: 'test-client',
        mcpClientVersion: '1.0.0',
        mcpProtocolVersion: LATEST_PROTOCOL_VERSION,
        requestStartTime: Date.now(),
        transport: 'streamable-http',
        userHash: 'test-user',
    }
}

async function call(method: string, params: Record<string, unknown> = {}): Promise<any> {
    const dispatcher = new McpDispatcher({} as any, {} as RedisLike)
    const response = await dispatcher.handleRequest(
        new Request('https://mcp.test/mcp', {
            body: JSON.stringify({ id: 1, jsonrpc: '2.0', method, params }),
            headers: { 'Content-Type': 'application/json' },
            method: 'POST',
        }),
        makeProps()
    )
    return await response.json()
}

describe('McpDispatcher skills extension', () => {
    beforeEach(() => {
        mockExecSkillsEnabled.mockReset().mockReturnValue(true)
        mockResolveState.mockReset().mockResolvedValue({ toolFeatureFlags: { 'mcp-skills-extension': true } })
        mockGetCatalog
            .mockReset()
            .mockReturnValue(SkillCatalog.fromZip(zipSync({ 'funnels/SKILL.md': strToU8(SKILL_MD) })))
    })

    it('advertises the extension and serves a listed skill end to end', async () => {
        const init = await call('initialize', { capabilities: {}, protocolVersion: LATEST_PROTOCOL_VERSION })
        expect(init.result.capabilities.extensions['io.modelcontextprotocol/skills']).toEqual({})

        const list = await call('skills/list')
        expect(list.result).toMatchObject({
            resultType: 'complete',
            cacheScope: 'private',
            ttlMs: expect.any(Number),
            skills: [{ uri: SKILL_URI, frontmatter: { name: 'funnels' } }],
        })

        const get = await call('skills/get', { uri: SKILL_URI })
        expect(get.result.skill).toEqual(list.result.skills[0])

        const read = await call('resources/read', { uri: SKILL_URI })
        expect(read.result.contents).toEqual([{ uri: SKILL_URI, mimeType: 'text/markdown', text: SKILL_MD }])
    })

    it.each([
        ['the extension flag is off', () => mockResolveState.mockResolvedValue({ toolFeatureFlags: {} })],
        ['the learn skill commands are off', () => mockExecSkillsEnabled.mockReturnValue(false)],
    ])('neither advertises nor serves skills when %s', async (_case, turnOff) => {
        turnOff()

        const init = await call('initialize', { capabilities: {}, protocolVersion: LATEST_PROTOCOL_VERSION })
        expect(init.result.capabilities.extensions).not.toHaveProperty('io.modelcontextprotocol/skills')
        expect((await call('skills/list')).result.skills).toEqual([])
        expect((await call('skills/get', { uri: SKILL_URI })).error.code).toBe(ErrorCode.InvalidParams)
    })

    it.each([
        ['skills/get', 'skill://missing/SKILL.md'],
        ['resources/read', 'skill://funnels/missing.md'],
    ])('answers %s for an unknown skill URI with Invalid params', async (method, uri) => {
        expect((await call(method, { uri })).error.code).toBe(ErrorCode.InvalidParams)
    })
})
