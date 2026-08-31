import { describe, expect, it } from 'vitest'

import {
    getPulseToolManifest,
    PULSE_ANALYSIS_TOOL_MANIFEST_V1,
    PULSE_EXECUTION_TOOL_MANIFEST_V1,
} from '@/lib/pulse-tool-manifest'
import { getToolDefinitions } from '@/tools/toolDefinitions'

const pulseReadScopes = [
    'action:read',
    'alert:read',
    'annotation:read',
    'cohort:read',
    'dashboard:read',
    'data_catalog:read',
    'error_tracking:read',
    'event_definition:read',
    'experiment:read',
    'feature_flag:read',
    'insight:read',
    'metrics:read',
    'property_definition:read',
    'query:read',
    'subscription:read',
    'warehouse_objects:read',
    'warehouse_table:read',
    'warehouse_view:read',
    'web_analytics:read',
]

const analysisScopes = [...pulseReadScopes, 'internal_run:read', 'llm_gateway:read']

describe('Pulse MCP tool manifest', () => {
    it('uses a fixed analysis catalog instead of every tool sharing its read scopes', () => {
        const manifest = getPulseToolManifest(analysisScopes)

        expect(manifest).toEqual(PULSE_ANALYSIS_TOOL_MANIFEST_V1)
        expect(manifest).not.toContain('execute-sql')
        expect(manifest).not.toContain('feature-flags-test-evaluation-create')
        expect(manifest).not.toContain('render-ui')
        expect(manifest).not.toContain('feedback-create')
    })

    it('adds only the experiment draft creator for the execution posture', () => {
        const manifest = getPulseToolManifest([...analysisScopes, 'pulse_experiment_draft:write'])

        expect(manifest).toEqual(PULSE_EXECUTION_TOOL_MANIFEST_V1)
        expect(manifest).toContain('experiment-pulse-draft-create')
        expect(manifest).not.toContain('experiment-create')
    })

    it('does not activate for a partial or broader token', () => {
        expect(getPulseToolManifest(analysisScopes.slice(1))).toBeUndefined()
        expect(getPulseToolManifest([...analysisScopes, 'task:write'])).toBeUndefined()
    })

    it('names only catalogued tools and rejects unlisted tools with approved scopes', () => {
        const definitions = getToolDefinitions()

        for (const toolName of PULSE_ANALYSIS_TOOL_MANIFEST_V1) {
            expect(definitions[toolName]).not.toBeUndefined()
            expect(definitions[toolName]?.annotations.readOnlyHint).toBe(true)
        }
        expect(definitions['execute-sql']?.required_scopes).toContain('query:read')
        expect(PULSE_ANALYSIS_TOOL_MANIFEST_V1).not.toContain('execute-sql')
    })
})
