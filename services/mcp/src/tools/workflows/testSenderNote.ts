function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasTestSenderLiveWarning(flow: unknown): boolean {
    const warnings = isRecord(flow) ? flow.warnings : undefined
    return (
        Array.isArray(warnings) &&
        warnings.some(
            (warning) =>
                isRecord(warning) &&
                warning.code === 'test_sender_live' &&
                typeof warning.message === 'string' &&
                warning.message.trim() !== ''
        )
    )
}

/**
 * The tool's agent_note in tools.yaml asks the agent to relay a test_sender_live warning, so it rides only on a
 * result whose workflow carries one.
 */
export function keepTestSenderNoteOnlyWithWarning(result: unknown, flow: unknown): unknown {
    if (!isRecord(result) || !('_agentNote' in result) || hasTestSenderLiveWarning(flow)) {
        return result
    }
    const { _agentNote: _dropped, ...rest } = result
    return rest
}
