import { describe, expect, it } from 'vitest'

import { InstructionsBuilder } from '@/hono/instructions'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { CODEX_INSTRUCTIONS_BUDGET_BYTES } from '@/lib/client-detection'
import type { ClientCapabilities } from '@/lib/client-detection'
import { getToolDefinitions } from '@/tools/toolDefinitions'

describe('InstructionsBuilder', () => {
    const metadataMarker = 'CURRENT PROJECT: Acme (timezone America/New_York)'

    const makeState = (capabilities: ClientCapabilities): ResolvedState =>
        ({
            useSingleExec: true,
            metadata: metadataMarker,
            groupTypes: [{ group_type: 'organization', group_type_index: 0, name_singular: null, name_plural: null }],
            allTools: Object.keys(getToolDefinitions()).map((name) => ({ name })),
            clientProfile: {
                capabilities,
                isClaudeChatHost: () => false,
            },
        }) as unknown as ResolvedState

    // Codex truncates `instructions` at 1000 bytes, so a budgeted client has to get the
    // bounded payload here and its env-context on the exec `command` description instead.
    // Wiring this to the unbounded builder would ship a payload Codex cuts mid-domain,
    // which is how the tool-domain index went missing for those sessions.
    it('splits the payload for a budgeted client', () => {
        const builder = new InstructionsBuilder('')
        const state = makeState({
            supportsInstructions: true,
            instructionsBudgetBytes: CODEX_INSTRUCTIONS_BUDGET_BYTES,
        })

        const instructions = builder.build(state)
        const commandReference = builder.buildExecCommandReference(state)

        expect(Buffer.byteLength(instructions, 'utf8')).toBeLessThanOrEqual(CODEX_INSTRUCTIONS_BUDGET_BYTES)
        expect(instructions.split('|')).toContain('skill')
        expect(instructions).not.toContain(metadataMarker)
        expect(commandReference).toContain(metadataMarker)
        expect(commandReference).toContain('Defined group types: organization')
    })

    it('keeps the full payload and strips env-context from the command for an unbudgeted client', () => {
        const builder = new InstructionsBuilder('')
        const state = makeState({ supportsInstructions: true })

        const instructions = builder.build(state)
        const commandReference = builder.buildExecCommandReference(state)

        expect(Buffer.byteLength(instructions, 'utf8')).toBeGreaterThan(CODEX_INSTRUCTIONS_BUDGET_BYTES)
        expect(instructions).toContain(metadataMarker)
        expect(commandReference).not.toContain(metadataMarker)
    })
})
