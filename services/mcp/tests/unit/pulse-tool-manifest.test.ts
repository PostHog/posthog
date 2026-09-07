import { describe, expect, it } from 'vitest'

import {
    filterPulseAnalysisTools,
    isPulseAnalysisScopePosture,
    PULSE_ANALYSIS_INTERNAL_SCOPE,
    PULSE_RESEARCH_INTERNAL_SCOPE,
} from '@/lib/pulse-tool-manifest'

describe('pulse analysis tool manifest', () => {
    it('admits only named tools for a server-minted Pulse token', () => {
        const scopes = [PULSE_ANALYSIS_INTERNAL_SCOPE, 'insight:read', 'query:read', 'task:write']
        const tools = [{ name: 'insight-query' }, { name: 'execute-sql' }, { name: 'insights-list' }]

        expect(isPulseAnalysisScopePosture(scopes)).toBe(true)
        expect(filterPulseAnalysisTools(tools, scopes).map((tool) => tool.name)).toEqual([
            'insight-query',
            'execute-sql',
        ])
    })

    it('does not select the Pulse manifest for an ordinary scoped token', () => {
        const tools = [{ name: 'insight-query' }, { name: 'insights-list' }]

        expect(filterPulseAnalysisTools(tools, ['insight:read']).map((tool) => tool.name)).toEqual([
            'insight-query',
            'insights-list',
        ])
    })

    it('keeps the manifest restricted when a marked token carries an unexpected write scope', () => {
        const tools = [{ name: 'insight-query' }, { name: 'feature-flags-create' }]
        const scopes = [PULSE_ANALYSIS_INTERNAL_SCOPE, 'feature_flag:write']

        expect(filterPulseAnalysisTools(tools, scopes).map((tool) => tool.name)).toEqual(['insight-query'])
    })

    it('withholds public research unless the marked token has its internal research scope', () => {
        const tools = [{ name: 'insight-query' }, { name: 'pulse-research-search' }]

        expect(
            filterPulseAnalysisTools(tools, [PULSE_ANALYSIS_INTERNAL_SCOPE, PULSE_RESEARCH_INTERNAL_SCOPE]).map(
                (tool) => tool.name
            )
        ).toEqual(['insight-query', 'pulse-research-search'])
        expect(filterPulseAnalysisTools(tools, [PULSE_ANALYSIS_INTERNAL_SCOPE]).map((tool) => tool.name)).toEqual([
            'insight-query',
        ])
    })
})
