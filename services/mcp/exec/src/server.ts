import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'

import { SnippetRunner } from './lib/runner'
import { Searcher, type SearchDoc } from './lib/searcher'
import { TypeReader } from './lib/type-reader'
import { ExecInputSchema, ExecTool } from './tools/exec-tool'
import { ReadInputSchema, ReadTool } from './tools/read-tool'
import { SearchInputSchema, SearchTool } from './tools/search-tool'

export interface ServerConfig {
    sdkDtsSource: string
    searchDocs: SearchDoc[]
    clientFactory: () => unknown
}

export class ExecMcpServer {
    private readonly mcp: McpServer
    private readonly searchTool: SearchTool
    private readonly readTool: ReadTool
    private readonly execTool: ExecTool

    constructor(config: ServerConfig) {
        this.mcp = new McpServer({ name: 'posthog-mcp-exec', version: '0.1.0' })

        const searcher = new Searcher(config.searchDocs)
        const typeReader = new TypeReader(config.sdkDtsSource)
        const runner = new SnippetRunner(config.clientFactory)

        this.searchTool = new SearchTool(searcher)
        this.readTool = new ReadTool(typeReader)
        this.execTool = new ExecTool(runner)

        this.registerTools()
    }

    get server(): McpServer {
        return this.mcp
    }

    private registerTools(): void {
        this.mcp.registerTool(
            'search',
            {
                title: 'Search SDK',
                description:
                    'Search for SDK operations and types by natural-language query. Returns ranked hits with one-line snippets. Empty query returns the full index, paginated. This is the entry point — call this first to discover what the SDK can do.',
                inputSchema: SearchInputSchema,
            },
            async (args) => {
                const result = this.searchTool.handle(args)
                return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] }
            }
        )

        this.mcp.registerTool(
            'read',
            {
                title: 'Read SDK type or operation',
                description:
                    'Fetch the TypeScript signature of an SDK operation (Client method) or a Schemas type, with one level of directly-referenced types inlined. Use this after `search` to get the full shape needed to write an `exec` snippet.',
                inputSchema: ReadInputSchema,
            },
            async (args) => {
                const result = this.readTool.handle(args)
                return { content: [{ type: 'text', text: result.source }] }
            }
        )

        this.mcp.registerTool(
            'exec',
            {
                title: 'Execute TypeScript snippet against the SDK client',
                description:
                    'Run a TypeScript snippet against a pre-bound `client` (see sdk.d.ts → Client interface). Snippet has `client`, `console`, and can `await`. Should `return` a value. Output includes stdout/stderr capture, the return value (truncated if large), and classified errors (syntax/runtime/http).',
                inputSchema: ExecInputSchema,
            },
            async (args) => {
                const result = await this.execTool.handle(args)
                return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] }
            }
        )
    }
}
