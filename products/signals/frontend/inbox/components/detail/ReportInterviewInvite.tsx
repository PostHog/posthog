import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { captureInboxInterviewInvite } from '../../inboxAnalytics'

function bookingUrlFromPayload(payload: unknown): string | null {
    if (typeof payload !== 'object' || payload === null || !('booking_url' in payload)) {
        return null
    }
    const bookingUrl = payload.booking_url
    if (typeof bookingUrl !== 'string') {
        return null
    }
    try {
        const url = new URL(bookingUrl)
        return url.protocol === 'https:' && (url.hostname === 'cal.com' || url.hostname.endsWith('.cal.com'))
            ? bookingUrl
            : null
    } catch {
        return null
    }
}

export function ReportInterviewInvite(): JSX.Element | null {
    const enabled = useFeatureFlag('INBOX_INTERVIEW_INVITE')
    const { user } = useValues(userLogic)
    const bookingUrl = enabled
        ? bookingUrlFromPayload(getFeatureFlagPayload(FEATURE_FLAGS.INBOX_INTERVIEW_INVITE))
        : null
    const dismissKey = `inbox-interview-invite-${user?.uuid ?? 'anonymous'}`
    const seenKey = `inbox-interview-invite-seen-${user?.uuid ?? 'anonymous'}`
    const wasShownBefore = useMemo(() => {
        try {
            return window.localStorage.getItem(seenKey) === '1'
        } catch {
            return true
        }
    }, [seenKey])
    const logic = lemonBannerLogic({ dismissKey })
    const { isDismissed } = useValues(logic)
    const { dismiss } = useActions(logic)

    useEffect(() => {
        if (enabled && user?.uuid && bookingUrl && !isDismissed && !wasShownBefore) {
            try {
                if (window.localStorage.getItem(seenKey) === '1') {
                    return
                }
                window.localStorage.setItem(seenKey, '1')
            } catch {
                return
            }
            captureInboxInterviewInvite('shown')
        }
    }, [enabled, user?.uuid, bookingUrl, isDismissed, wasShownBefore, seenKey])

    if (!enabled || !user?.uuid || !bookingUrl || isDismissed || wasShownBefore) {
        return null
    }

    return (
        <div
            className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs text-tertiary"
            onKeyDown={(event) => {
                if (event.key === 'Enter') {
                    event.stopPropagation()
                }
            }}
        >
            <span>Want some free PostHog merch?</span>
            <LemonButton
                type="tertiary"
                size="xsmall"
                to={bookingUrl}
                targetBlank
                onClick={() => {
                    captureInboxInterviewInvite('clicked')
                    dismiss()
                }}
                data-attr="inbox-interview-invite-book"
            >
                Book a 30-minute chat about Inbox
            </LemonButton>
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={<IconX />}
                aria-label="Dismiss interview invite"
                onClick={() => {
                    captureInboxInterviewInvite('dismissed')
                    dismiss()
                }}
            />
        </div>
    )
}
