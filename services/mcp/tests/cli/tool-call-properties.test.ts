import { describe, expect, it } from 'vitest'

import { buildToolCallProperties } from '@/cli/tool-call-properties'
import type { ExecInnerCallProperties } from '@/tools/exec'

// The CLI flushes these events on the error path, so anything value-carrying
// here (raw error messages, inputs) would ship caller content and API response
// bodies to usage analytics. `toEqual` pins the exact shape: reintroducing
// `error_message` or `input` fails every case below.
describe('buildToolCallProperties', () => {
    const base: ExecInnerCallProperties = {
        duration_ms: 42,
        success: false,
        output_format: 'text',
        error_message: 'API error: {"detail": "secret notebook content …"}',
        input: { markdown: 'private caller-supplied text' },
    }

    it('never forwards error_message or input, only a value-free classification', () => {
        expect(buildToolCallProperties('notebook-edit', base)).toEqual({
            tool_name: 'notebook-edit',
            $mcp_tool_name: 'notebook-edit',
            $mcp_duration_ms: 42,
            $mcp_is_error: true,
            output_format: 'text',
            error_class: 'error',
        })
    })

    it.each([
        ['schema rejection', { validation_error: true }, { error_class: 'validation_error' }],
        ['typed API failure', { error_status: 429 }, { error_class: 'api_error', error_status: 429 }],
    ])('classifies a %s without carrying the message', (_name, extra, expected) => {
        expect(buildToolCallProperties('feature-flag-get-all', { ...base, ...extra })).toEqual({
            tool_name: 'feature-flag-get-all',
            $mcp_tool_name: 'feature-flag-get-all',
            $mcp_duration_ms: 42,
            $mcp_is_error: true,
            output_format: 'text',
            ...expected,
        })
    })

    it('omits error fields entirely on success', () => {
        expect(buildToolCallProperties('feature-flag-get-all', { ...base, success: true })).toEqual({
            tool_name: 'feature-flag-get-all',
            $mcp_tool_name: 'feature-flag-get-all',
            $mcp_duration_ms: 42,
            $mcp_is_error: false,
            output_format: 'text',
        })
    })
})
