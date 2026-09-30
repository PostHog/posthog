import { waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { webmcpLogic } from './webmcpLogic'

interface RegisteredTool {
    name: string
    inputSchema?: Record<string, unknown>
    execute: (input: Record<string, unknown>) => Promise<string>
}

describe('webmcpLogic', () => {
    let registerTool: jest.Mock
    let postedCommands: string[]

    beforeEach(() => {
        registerTool = jest.fn().mockResolvedValue(undefined)
        postedCommands = []
        Object.defineProperty(document, 'modelContext', { value: { registerTool }, configurable: true })

        useMocks({
            get: {
                '/api/projects/:team/webmcp/tool/': () => [
                    200,
                    { name: 'exec', description: 'Run PostHog commands', input_schema: { type: 'object' } },
                ],
            },
            post: {
                '/api/projects/:team/webmcp/exec/': async ({ request }) => {
                    const { command } = (await request.json()) as { command: string }
                    postedCommands.push(command)
                    return command === 'call broken-tool {}'
                        ? [200, { content: [{ type: 'text', text: 'Tool failed' }], is_error: true }]
                        : [200, { content: [{ type: 'text', text: 'insight-get' }], is_error: false }]
                },
            },
        })

        initKeaTests()
        webmcpLogic.mount()
    })

    afterEach(() => {
        webmcpLogic.unmount()
        delete (document as Document & { modelContext?: unknown }).modelContext
    })

    it('registers the exec tool and forwards each call to the proxy', async () => {
        await waitFor(() => expect(registerTool).toHaveBeenCalled())
        const tool: RegisteredTool = registerTool.mock.calls[0][0]

        expect(tool.name).toEqual('exec')
        await expect(tool.execute({ command: 'search insights' })).resolves.toEqual('insight-get')
        await expect(tool.execute({ command: 'call broken-tool {}' })).rejects.toThrow('Tool failed')
        expect(postedCommands).toEqual(['search insights', 'call broken-tool {}'])
    })
})
