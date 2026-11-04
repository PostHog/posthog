import { IconLock } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import type { TransactionalEmailLogDetailApi } from 'products/messaging/frontend/generated/api.schemas'

import { getMessageAssetContentUrl } from '../../Workflows/messageAssetsApi'

export function TransactionalEmailRendered({ email }: { email: TransactionalEmailLogDetailApi }): JSX.Element {
    if (email.sensitive) {
        return (
            <LemonBanner type="info" icon={<IconLock />}>
                This email is marked sensitive, so PostHog keeps no copy of what it contained.
            </LemonBanner>
        )
    }
    if (!email.action_id) {
        return (
            <LemonBanner type="info">
                {email.status === 'failed' || email.status === 'queued'
                    ? "This email wasn't sent, so there's no copy of it."
                    : 'No copy of this email was kept.'}
            </LemonBanner>
        )
    }
    return (
        <section className="border rounded bg-surface-primary overflow-hidden">
            <dl className="ph-no-capture m-0 px-4 py-3 border-b grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-secondary">To</dt>
                <dd className="m-0 truncate">{email.recipient}</dd>
                <dt className="text-secondary">Subject</dt>
                <dd className="m-0 font-semibold truncate">{email.subject || '(no subject)'}</dd>
            </dl>
            {/* sandbox="" disables scripts so the captured email HTML can't run anything. */}
            <iframe
                title="Rendered email"
                sandbox=""
                src={getMessageAssetContentUrl(email.workflow_id, email.message_id, email.action_id)}
                className="w-full h-[70vh] bg-white block"
            />
        </section>
    )
}
