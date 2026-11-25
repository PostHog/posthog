import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

export function QuillLogsAlertsBetaBanner({ dismissKey }: { dismissKey: string }): JSX.Element | null {
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey }))
    const { dismiss } = useActions(lemonBannerLogic({ dismissKey }))

    if (isDismissed) {
        return null
    }

    return (
        <Item tone="info" size="sm" className="flex-wrap">
            <ItemContent>
                <ItemDescription>
                    Logs alerting is in beta. Alerts are checked every 5 minutes. Read the{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to="https://posthog.com/docs/logs/alerts" target="_blank" />}
                    >
                        docs
                    </Button>{' '}
                    or share feedback with what you'd like to see.
                </ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button variant="outline" id="logs-alerts-feedback-button">
                    Send feedback
                </Button>
                <Button size="icon" aria-label="Dismiss" tooltip="Dismiss" onClick={dismiss}>
                    <IconX />
                </Button>
            </ItemActions>
        </Item>
    )
}
