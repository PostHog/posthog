import { forwardRef } from 'react'

import { Link } from '@posthog/lemon-ui'

import type { LinkProps } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

// A Tooltip around the link passes its trigger props and ref through here to the anchor.
type RunLinkTagSettingsLinkProps = Pick<
    LinkProps,
    'className' | 'children' | 'onClick' | 'onFocus' | 'onMouseEnter' | 'onMouseLeave' | 'onKeyDown'
> &
    React.AriaAttributes & {
        dataAttr: string
        onOpen?: () => void
    }

export const RunLinkTagSettingsLink = forwardRef<HTMLElement, RunLinkTagSettingsLinkProps>(
    function RunLinkTagSettingsLink({ dataAttr, onOpen, ...props }, ref): JSX.Element {
        return (
            <Link
                {...props}
                ref={ref}
                to={urls.settings('environment-workflows', 'workflows-email-run-link-tag')}
                // A new tab keeps this page mounted, so an edit it hasn't saved yet survives the trip.
                target="_blank"
                data-attr={dataAttr}
                // Every mouse button presses down first, including the right button that opens the browser's
                // "Open link in new tab" menu. Capture also sees the keyboard's click and a Cmd-click or
                // Ctrl-click, which Link's own click handler swallows.
                onMouseDown={onOpen}
                onClickCapture={onOpen}
            />
        )
    }
)
