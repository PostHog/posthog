import { useActions } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'
import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { truncate } from 'lib/utils/strings'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { ErrorTrackingRule } from './types'

export function DisabledRuleBanner({ rule, onClose }: { rule: ErrorTrackingRule; onClose?: () => void }): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const rawMessage = rule.disabled_data ? (rule.disabled_data as Record<string, any>).message : null
    const message = rawMessage ? truncate(rawMessage, 200) : null

    const contactSupport = (): void => {
        openSidePanel(SidePanelTab.Support, 'bug:error_tracking')
        onClose?.()
    }

    if (todayRailNav) {
        return (
            <Item tone="warning" size="sm">
                <ItemContent>
                    <ItemDescription>
                        This rule has been disabled due to an error. Saving will re-enable it.
                    </ItemDescription>
                    {message && (
                        <ItemDescription>
                            <span>Error: </span>
                            <span translate="no">{message}</span>
                        </ItemDescription>
                    )}
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" onClick={contactSupport}>
                        Contact support
                    </Button>
                </ItemActions>
            </Item>
        )
    }

    return (
        <LemonBanner
            type="warning"
            action={{
                onClick: contactSupport,
                children: 'Contact support',
            }}
        >
            This rule has been disabled due to an error. Saving will re-enable it.
            {message && <div className="mt-1 text-xs text-muted">Error: {message}</div>}
        </LemonBanner>
    )
}
