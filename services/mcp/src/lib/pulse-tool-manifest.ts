export const PULSE_ANALYSIS_INTERNAL_SCOPE = 'pulse_analysis_internal:read'

export const PULSE_ANALYSIS_TOOL_MANIFEST_V1 = new Set([
    'execute-sql',
    'insight-query',
    'pulse-research-search',
    'read-data-schema',
])

export function isPulseAnalysisScopePosture(scopes: readonly string[]): boolean {
    return scopes.includes(PULSE_ANALYSIS_INTERNAL_SCOPE)
}

export function filterPulseAnalysisTools<T extends { name: string }>(tools: T[], scopes: readonly string[]): T[] {
    if (!isPulseAnalysisScopePosture(scopes)) {
        return tools
    }
    return tools.filter((tool) => PULSE_ANALYSIS_TOOL_MANIFEST_V1.has(tool.name))
}
