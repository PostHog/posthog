import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { InboxQuickSetupAction } from './InboxQuickSetupAction'

export function InboxSetupActions(): JSX.Element {
    const { continueFromWelcome } = useActions(inboxSetupLogic)
    const { saving } = useValues(inboxSetupLogic)

    return (
        <div className="flex w-full min-w-0 flex-col gap-4">
            <InboxQuickSetupAction />
            <div data-attr="inbox-welcome-set-up-manually" className="self-start">
                <Link
                    subtle
                    className="inline-flex items-center font-semibold"
                    onClick={continueFromWelcome}
                    disabled={saving}
                    // pinned: data-attr - the welcome funnel and test selectors match on this string
                    data-attr="inbox-setup-welcome-continue"
                >
                    Start manually
                    <IconChevronRight />
                </Link>
            </div>
        </div>
    )
}
