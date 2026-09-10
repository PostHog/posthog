import { describe, expect, it } from 'vitest'

import { buildToolCallProperties } from '@/cli/tool-call-properties'
import type { ExecInnerCallProperties } from '@/tools/exec'
import { getToolCategory, getToolDescription } from '@/tools/toolDefinitions'

// The CLI flushes these events on the error path, so anything value-carrying
// here (raw error messages, inputs) would ship caller content and API response
// bodies to usage analytics. `toEqual` pins the exact shape: reintroducing
// `error_message` or `input` fails every case below. Catalog metadata
// (category, clipped description) is safe by construction: it comes from the
// tool registry, never from the caller.
describe('buildToolCallProperties', () => {
    const base: ExecInnerCallProperties = {
        duration_ms: 42,
        success: false,
        output_format: 'text',
        error_message: 'API error: {"detail": "secret notebook content …"}',
        input: { markdown: 'private caller-supplied text' },
    }

    function catalogMetadata(toolName: string): Record<string, unknown> {
        return {
            $mcp_tool_category: getToolCategory(toolName),
            $mcp_tool_description: getToolDescription(toolName),
        }
    }

    it('never forwards error_message or input, only a value-free classification', () => {
        expect(buildToolCallProperties('notebook-edit', base)).toEqual({
            tool_name: 'notebook-edit',
            $mcp_tool_name: 'notebook-edit',
            $mcp_duration_ms: 42,
            $mcp_is_error: true,
            output_format: 'text',
            error_class: 'error',
            $mcp_error_type: 'internal',
            ...catalogMetadata('notebook-edit'),
        })
    })

    // `$mcp_error_type`/`$mcp_error_status` mirror the hosted server's vocabulary so
    // the MCP analytics failure tools can bucket CLI errors instead of showing them
    // as typeless.
    it.each([
        [
            'schema rejection',
            { validation_error: true },
            { error_class: 'validation_error', $mcp_error_type: 'validation' },
        ],
        [
            'rate-limited API failure',
            { error_status: 429 },
            { error_class: 'api_error', error_status: 429, $mcp_error_type: 'rate_limited', $mcp_error_status: 429 },
        ],
        [
            'permission API failure',
            { error_status: 403 },
            { error_class: 'api_error', error_status: 403, $mcp_error_type: 'permission', $mcp_error_status: 403 },
        ],
        [
            'client API failure',
            { error_status: 404 },
            { error_class: 'api_error', error_status: 404, $mcp_error_type: 'api_4xx', $mcp_error_status: 404 },
        ],
        [
            'server API failure',
            { error_status: 502 },
            { error_class: 'api_error', error_status: 502, $mcp_error_type: 'api_5xx', $mcp_error_status: 502 },
        ],
    ])('classifies a %s without carrying the message', (_name, extra, expected) => {
        expect(buildToolCallProperties('feature-flag-get-all', { ...base, ...extra })).toEqual({
            tool_name: 'feature-flag-get-all',
            $mcp_tool_name: 'feature-flag-get-all',
            $mcp_duration_ms: 42,
            $mcp_is_error: true,
            output_format: 'text',
            ...catalogMetadata('feature-flag-get-all'),
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
            ...catalogMetadata('feature-flag-get-all'),
        })
    })

    it('stamps catalog metadata on catalogued tools and omits it for unknown names', () => {
        // The CLI path silently shipped without category or description while the
        // hosted server stamped both; this pins the two paths to the same catalog.
        const catalogued = buildToolCallProperties('feature-flag-get-all', { ...base, success: true })
        expect(catalogued.$mcp_tool_category).toBeTruthy()
        expect(catalogued.$mcp_tool_description).toBeTruthy()

        const unknown = buildToolCallProperties('not-a-real-tool', { ...base, success: true })
        expect(unknown).not.toHaveProperty('$mcp_tool_category')
        expect(unknown).not.toHaveProperty('$mcp_tool_description')
    })
})
