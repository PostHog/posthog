/**
 * Legacy `initialize` handshake handler.
 *
 * Negotiates protocol version, caches the client's declared elicitation
 * capability for the v1 dispatcher to consult on subsequent `tools/call`
 * requests, builds the per-request instructions string, and emits init
 * analytics.
 */

import {
    LATEST_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    type InitializeResult,
    type JSONRPCRequest,
} from '@modelcontextprotocol/sdk/types.js'

import { MCP_SERVER_NAME, MCP_SERVER_VERSION } from '@/lib/constants'
import type { RequestProperties } from '@/lib/request-properties'

import { trackInitEvent } from '../../analytics'
import { type CachedClientCapabilities, CapabilityStore, projectClientCapabilities } from '../../capability-store'
import { InstructionsBuilder } from '../../instructions'
import { initDurationSeconds, initTotal } from '../../metrics'
import type { HandshakeStrategy } from '../../protocol-strategy'
import type { ResolvedState } from '../../request-state-resolver'

export class LegacyHandshakeStrategy implements HandshakeStrategy {
    readonly method = 'initialize'

    constructor(
        private readonly capabilityStore: CapabilityStore,
        private readonly instructionsBuilder: InstructionsBuilder
    ) {}

    async handle(request: JSONRPCRequest, props: RequestProperties, state: ResolvedState): Promise<InitializeResult> {
        const params = request.params as Record<string, unknown> | undefined
        try {
            const requestedVersion = (params?.['protocolVersion'] as string) ?? LATEST_PROTOCOL_VERSION
            const protocolVersion = SUPPORTED_PROTOCOL_VERSIONS.includes(requestedVersion)
                ? requestedVersion
                : LATEST_PROTOCOL_VERSION

            // Cache the client's declared capabilities for subsequent
            // stateless requests to gate elicitation/create. Always
            // overwrite — a re-initialize with FEWER capabilities than a
            // prior session must downgrade.
            const projectedCaps: CachedClientCapabilities = projectClientCapabilities(params?.['capabilities'])
            await this.capabilityStore.set(props.userHash, projectedCaps)

            const instructions = await this.instructionsBuilder.build(props, state)

            initDurationSeconds.observe(props.requestStartTime ? (Date.now() - props.requestStartTime) / 1000 : 0)
            initTotal.inc({ status: 'success' })

            void trackInitEvent(props, state)

            return {
                protocolVersion,
                capabilities: {
                    tools: { listChanged: false },
                    resources: { listChanged: false },
                    prompts: { listChanged: false },
                },
                serverInfo: { name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION },
                ...(instructions ? { instructions } : {}),
            }
        } catch (error) {
            initTotal.inc({ status: 'error' })
            throw error
        }
    }
}
