import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function RunLinkTagSettingsLink({
    className,
    dataAttr,
    onOpen,
    children,
}: {
    className?: string
    dataAttr: string
    onOpen?: () => void
    children: React.ReactNode
}): JSX.Element {
    return (
        <Link
            to={urls.settings('environment-workflows', 'workflows-email-run-link-tag')}
            // A new tab keeps this page mounted, so an edit it hasn't saved yet survives the trip.
            target="_blank"
            className={className}
            data-attr={dataAttr}
            // Capture runs before Link's own click handler, which swallows a Cmd-click or Ctrl-click.
            onClickCapture={onOpen}
            onAuxClick={onOpen}
        >
            {children}
        </Link>
    )
}
