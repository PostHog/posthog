import { IconCode } from '@posthog/icons'
import { LemonCard, Link } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { FirstSendStatus } from './FirstSendStatus'
import { SendFromCodeSetup } from './SendFromCodeSetup'
import { SendingDomainRow } from './SendingDomainRow'

export function SendFromCodeEmptyState(): JSX.Element {
    const canCreateTemplate = !getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor
    )

    return (
        <div className="flex flex-col items-center py-8" data-attr="send-from-code-empty-state">
            <div className="flex flex-col gap-4 w-full max-w-180">
                <div className="flex flex-col items-center gap-1 text-center">
                    <IconCode className="text-3xl text-secondary" />
                    <h2 className="m-0 text-xl font-bold">Send your first email from code</h2>
                    <p className="m-0 text-secondary">
                        Password resets, receipts and sign-in codes: one API call from your server sends the email, and
                        PostHog links it to the person who got it.
                    </p>
                </div>
                <SendingDomainRow />
                <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
                    <h3 className="m-0 text-base font-semibold">Add the send to your server code</h3>
                    <SendFromCodeSetup surface="transactional" />
                </LemonCard>
                <FirstSendStatus surface="transactional" />
                {canCreateTemplate ? (
                    <p className="m-0 text-center text-secondary text-sm">
                        Want to design the email in PostHog instead?{' '}
                        <Link to={urls.transactionalNew()} data-attr="send-from-code-create-template">
                            Create a template
                        </Link>
                    </p>
                ) : null}
            </div>
        </div>
    )
}
