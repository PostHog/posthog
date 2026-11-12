import { useActions } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconBell, IconWarning } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { urlForSubscriptions } from 'products/subscriptions/frontend/components/Subscriptions/utils'

import { QuillInsightSubscribeButton } from './QuillInsightSubscribeButton'

interface QuillInsightMonitorButtonProps {
    insightShortId: InsightShortId
    canCreateAlert: boolean
}

export function QuillInsightMonitorButton({
    insightShortId,
    canCreateAlert,
}: QuillInsightMonitorButtonProps): JSX.Element {
    const { push } = useActions(router)

    if (!canCreateAlert) {
        return <QuillInsightSubscribeButton insightShortId={insightShortId} />
    }

    const open = (option: 'alerts' | 'subscriptions', url: string): void => {
        posthog.capture('insight notify prominent button clicked', { insight_short_id: insightShortId, option })
        push(url)
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="outline" data-attr="insight-notify-prominent-button" />}>
                <IconBell />
                Monitor
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuItem
                    description="Notify me when the insight meets a condition"
                    onClick={() => open('alerts', urls.insightAlerts(insightShortId))}
                >
                    <IconWarning />
                    Alerts
                </DropdownMenuItem>
                <DropdownMenuItem
                    description="Send me a recurring report"
                    onClick={() => open('subscriptions', urlForSubscriptions({ insightShortId }))}
                >
                    <IconBell />
                    Subscriptions
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
