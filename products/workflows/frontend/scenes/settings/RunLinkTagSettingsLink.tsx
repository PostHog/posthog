import { useActions } from 'kea'
import { useEffect } from 'react'

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

    // The setting changes in the settings tab this link opens, and the reader can come back before or
    // after saving it there, so reload the team on every return while this link is on the page.
    useEffect(() => {
        const onFocus = (): void => {
            refreshCurrentTeam()
        }
        window.addEventListener('focus', onFocus)
        return () => window.removeEventListener('focus', onFocus)
    }, [refreshCurrentTeam])

    return (
        <Link
            to={urls.settings('environment-workflows', 'workflows-email-run-link-tag')}
            // A new tab keeps this page mounted, so an edit it hasn't saved yet survives the trip.
            target="_blank"
            className={className}
            data-attr={dataAttr}
        >
            {children}
        </Link>
    )
}
