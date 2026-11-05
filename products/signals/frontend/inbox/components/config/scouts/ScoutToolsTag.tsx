import { useValues } from 'kea'

import { IconWrench } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

/**
 * Marks a scout limited to a chosen tool list. A scout that can call every tool gets no tag, because
 * that is the default.
 */
export function ScoutToolsTag({
    allowedTools,
    compact = false,
}: {
    /** The scout's `allowed_mcp_tools`. Null means every tool. */
    allowedTools: readonly string[] | null | undefined
    /** Icon only, for a row too narrow to carry the label. The tooltip still gives the count. */
    compact?: boolean
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCOUTS_TOOL_ACCESS] || allowedTools == null) {
        return null
    }
    const label = `${allowedTools.length} ${allowedTools.length === 1 ? 'tool' : 'tools'}`
    return (
        <Tooltip title={`This scout can call only its ${label} chosen in settings, plus its built-in run tools`}>
            <LemonTag size="small" type="muted" icon={<IconWrench />} data-attr="scout-tools-tag">
                {compact ? null : label}
            </LemonTag>
        </Tooltip>
    )
}
