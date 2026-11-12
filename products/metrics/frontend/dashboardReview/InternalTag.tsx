import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export const INTERNAL_TAG_TOOLTIP = 'Only PostHog staff can see this.'

export function InternalTag(): JSX.Element {
    return (
        <Tooltip title={INTERNAL_TAG_TOOLTIP}>
            <LemonTag type="highlight" size="small" data-attr="metrics-dashboard-review-internal-tag">
                Internal
            </LemonTag>
        </Tooltip>
    )
}
