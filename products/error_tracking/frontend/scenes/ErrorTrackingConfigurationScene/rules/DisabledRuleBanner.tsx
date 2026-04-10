import { useActions } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { truncate } from 'lib/utils'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { ErrorTrackingRule } from './types'

export function DisabledRuleBanner({ rule, onClose }: { rule: ErrorTrackingRule; onClose?: () => void }): JSX.Element {
    const { openSidePanel } = useActions(sidePanelLogic)
    const rawMessage = rule.disabled_data ? (rule.disabled_data as Record<string, any>).message : null
    const message = rawMessage ? truncate(rawMessage, 200) : null

    return (
        <LemonBanner
            type="warning"
            action={{
                onClick: () => {
                    openSidePanel(SidePanelTab.Support, 'bug:error_tracking')
                    onClose?.()
                },
                children: 'Contact support',
            }}
        >
            This rule has been disabled due to an error. Saving will re-enable it.
            {message && <div className="mt-1 text-xs text-muted">Error: {message}</div>}
        </LemonBanner>
    )
}
