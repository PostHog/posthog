import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function RunLinkTagSettingsLink({
    className,
    dataAttr,
    children,
}: {
    className?: string
    dataAttr: string
    children: React.ReactNode
}): JSX.Element {
    const { refreshCurrentTeam } = useActions(teamLogic)
    const pendingRefresh = useRef<(() => void) | null>(null)

    useEffect(
        () => () => {
            if (pendingRefresh.current) {
                window.removeEventListener('focus', pendingRefresh.current)
            }
        },
        []
    )

    // The setting changes in another tab, so reload the team once when this tab gets focus back.
    const refreshOnReturn = (): void => {
        if (pendingRefresh.current) {
            return
        }
        const onFocus = (): void => {
            pendingRefresh.current = null
            refreshCurrentTeam()
        }
        pendingRefresh.current = onFocus
        window.addEventListener('focus', onFocus, { once: true })
    }

    return (
        <Link
            to={urls.settings('environment-workflows', 'workflows-email-run-link-tag')}
            // A new tab keeps this page mounted, so an edit it hasn't saved yet survives the trip.
            target="_blank"
            // Capture also sees Cmd/Ctrl-clicks, and middle-clicks only fire auxclick.
            onClickCapture={refreshOnReturn}
            onAuxClick={refreshOnReturn}
            className={className}
            data-attr={dataAttr}
        >
            {children}
        </Link>
    )
}
