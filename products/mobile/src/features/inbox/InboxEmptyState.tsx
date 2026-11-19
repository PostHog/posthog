import * as Clipboard from 'expo-clipboard'
import * as WebBrowser from 'expo-web-browser'
import { type ReactElement, useEffect, useState } from 'react'

import { ApiError } from '@/api/client'
import type { InboxStatusApi } from '@/api/inboxStatus'
import { useProjectScope } from '@/auth/useProjectScope'
import { track } from '@/lib/analytics'
import { useAsyncAction } from '@/lib/useAsyncAction'
import type { QueryState } from '@/model/types'
import { InboxIcon } from '@/ui/icons/InboxIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LoadingView, StateView } from '@/ui/StateView'
import { useColors } from '@/ui/theme'
import { iconSizes } from '@/ui/tokens'

import { type InboxEmptyKind, inboxEmptyKind, inboxSetupUrl } from './inboxSetupState'

const COPY: Record<InboxEmptyKind, { title: string; message: string; action?: string }> = {
    not_started: {
        title: 'Set up self-driving',
        message: 'Let PostHog investigate your product data and bring you reports with evidence and next steps.',
        action: 'Continue on web',
    },
    in_progress: {
        title: 'Finish setting up self-driving',
        message: 'Your project has a setup in progress. Continue on the web to start receiving reports here.',
        action: 'Continue setup on web',
    },
    paused: {
        title: 'Self-driving is paused',
        message:
            'Your project has no active sources or scouts sending reports. Review your settings to start receiving them again.',
        action: 'Review settings',
    },
    ai_disabled: {
        title: 'AI data processing is off',
        message:
            'An organization admin needs to enable AI data processing before self-driving can investigate your product.',
        action: 'Review settings',
    },
    pending: {
        title: 'Checking your project',
        message: 'PostHog is checking which data is available for your first investigation.',
    },
    running: {
        title: 'Looking for your first report',
        message: 'PostHog is investigating your project for something you can act on. You can come back later.',
    },
    no_data: {
        title: 'Waiting for product data',
        message:
            'Self-driving is set up, but there is no data to investigate yet. Check that your project is sending data.',
        action: 'Review setup on web',
    },
    insufficient_data: {
        title: 'More data is needed',
        message: 'The first investigation finished, but there is not enough data yet for a reliable report.',
        action: 'Review setup on web',
    },
    no_actionable_finding: {
        title: 'Your first investigation is complete',
        message: 'PostHog checked your data and did not find anything worth reporting yet.',
    },
    incomplete: {
        title: "Your first investigation couldn't finish",
        message: 'Review your connections and investigation activity on the web to find out what happened.',
        action: 'Review setup on web',
    },
    waiting: {
        title: 'Waiting for your first report',
        message:
            'Self-driving is set up. Reports will appear here when PostHog finds something that needs your attention.',
    },
    quiet: {
        title: 'Nothing needs you right now',
        message: 'New reports show up here when PostHog finds something worth a look.',
    },
}

export function InboxEmptyState({
    status,
    onRefresh,
}: {
    status: QueryState<InboxStatusApi>
    onRefresh: () => void
}): ReactElement {
    const colors = useColors()
    const scope = useProjectScope()
    const [feedback, setFeedback] = useState<string | null>(null)
    const kind = status.data ? inboxEmptyKind(status.data) : null
    const unavailable = status.error instanceof ApiError && [403, 404].includes(status.error.status)
    const url = inboxSetupUrl(scope, kind ?? 'unavailable')
    useEffect(() => {
        setFeedback(null)
        if (kind && scope) track('mobile_inbox_state_shown', { state: kind, can_configure: status.data?.can_configure })
    }, [kind, scope, status.data?.can_configure])
    const open = useAsyncAction(async () => {
        if (!url) return
        track('mobile_inbox_setup_opened', { state: kind ?? 'unavailable' })
        try {
            await WebBrowser.openBrowserAsync(url)
            void status.refetch()
            onRefresh()
        } catch {
            setFeedback("Couldn't open the browser. Try again or copy the setup link.")
        }
    })
    const copy = useAsyncAction(async () => {
        if (!url) return
        try {
            await Clipboard.setStringAsync(url)
            setFeedback('Link copied. Open it on a computer or share it with a project admin.')
            track('mobile_inbox_setup_link_copied', { state: kind ?? 'unavailable' })
        } catch {
            setFeedback("Couldn't copy the link. Try again.")
        }
    })
    if (status.isLoading) return <LoadingView label="Checking self-driving setup" />
    if (!kind)
        return (
            <StateView
                icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                title={unavailable ? 'Self-driving status is unavailable' : "Couldn't check self-driving setup"}
                message={
                    feedback ??
                    (unavailable
                        ? 'Open the web inbox to check this project’s setup and your access.'
                        : 'Check your connection and try again.')
                }
                actionLabel={unavailable ? 'Open inbox on web' : 'Try again'}
                onAction={
                    unavailable
                        ? () => void open.run()
                        : () => {
                              void status.refetch()
                              onRefresh()
                          }
                }
                actionDisabledReason={
                    unavailable && !url ? 'Choose a project to continue' : open.pending ? 'Opening browser…' : undefined
                }
                testID="inbox-setup-error"
            />
        )
    const copyForState = COPY[kind]
    const needsPermission = !!copyForState.action && status.data?.can_configure === false && kind !== 'ai_disabled'
    return (
        <StateView
            icon={<InboxIcon size={iconSizes.empty} color={colors.tertiary} />}
            title={copyForState.title}
            message={
                feedback ??
                (needsPermission
                    ? `${copyForState.message} Ask a project admin to help with setup.`
                    : copyForState.message)
            }
            actionLabel={needsPermission ? 'Copy setup link' : copyForState.action}
            onAction={copyForState.action ? () => void (needsPermission ? copy.run() : open.run()) : undefined}
            actionDisabledReason={!url ? 'Not available in the demo' : open.pending ? 'Opening browser…' : undefined}
            secondaryActionLabel={
                copyForState.action && url ? (needsPermission ? 'Open on web' : 'Copy setup link') : undefined
            }
            onSecondaryAction={() => void (needsPermission ? open.run() : copy.run())}
            testID={kind === 'quiet' ? 'inbox-empty' : `inbox-${kind}`}
        />
    )
}
