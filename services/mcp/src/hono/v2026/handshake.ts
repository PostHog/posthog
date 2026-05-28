/**
 * v2026 `server/discover` handshake handler.
 *
 * Returns the static-per-build server info, the list of supported protocol
 * versions, the server-side capabilities (tools/resources/prompts), and
 * the per-request instructions.
 */

import type { JSONRPCRequest } from '@modelcontextprotocol/sdk/types.js'

import { MCP_SERVER_NAME, MCP_SERVER_VERSION } from '@/lib/constants'
import type { RequestProperties } from '@/lib/request-properties'

import type { InstructionsBuilder } from '../instructions'
import type { HandshakeStrategy } from '../protocol-strategy'
import type { ResolvedState } from '../request-state-resolver'
import { PROTOCOL_VERSION_2025_06_18, PROTOCOL_VERSION_2026_07_28 } from './constants'

export interface DiscoverResult {
    supportedVersions: string[]
    capabilities: {
        tools: { listChanged: boolean }
        resources: { listChanged: boolean }
        prompts: { listChanged: boolean }
    }
    serverInfo: { name: string; version: string }
    instructions?: string
}

export class V2026HandshakeStrategy implements HandshakeStrategy {
    readonly method = 'server/discover'

    constructor(private readonly instructionsBuilder: InstructionsBuilder) {}

    async handle(_request: JSONRPCRequest, props: RequestProperties, state: ResolvedState): Promise<DiscoverResult> {
        const instructions = await this.instructionsBuilder.build(props, state)
        const result: DiscoverResult = {
            supportedVersions: [PROTOCOL_VERSION_2026_07_28, PROTOCOL_VERSION_2025_06_18],
            capabilities: {
                tools: { listChanged: false },
                resources: { listChanged: false },
                prompts: { listChanged: false },
            },
            serverInfo: { name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION },
        }
        if (instructions) {
            result.instructions = instructions
        }
        return result
    }
}
