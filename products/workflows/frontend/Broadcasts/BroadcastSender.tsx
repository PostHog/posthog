import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { type BroadcastEmailValue, broadcastWizardLogic, getSenderIds } from './broadcastWizardLogic'

/** The name and address the email goes out from, one line per sender. */
export function BroadcastSender(): JSX.Element {
    const { email, integrations, integrationsLoading } = useValues(broadcastWizardLogic)
    // A broadcast saved through the API or the workflow editor can set its own name and address.
    const from: BroadcastEmailValue['from'] & { name?: string; email?: string } = email.from ?? {}
    const senderIds = getSenderIds(from)

    if (senderIds.length === 0) {
        return <span className="text-muted">No sender</span>
    }
    if (!integrations && integrationsLoading) {
        return <Spinner />
    }
    return (
        <div className="flex flex-col gap-0.5">
            {senderIds.map((id) => {
                const sender = integrations?.find(
                    (integration) => integration.kind === 'email' && integration.id === id
                )
                const name = from.name || sender?.config?.name
                const address = from.email || sender?.config?.email
                return (
                    <span key={id} className="wrap-anywhere">
                        {!sender ? (
                            <span className="text-muted">
                                {integrations ? 'Deleted sender' : "Couldn't load the sender"}
                            </span>
                        ) : name ? (
                            `${name} <${address}>`
                        ) : (
                            address
                        )}
                    </span>
                )
            })}
        </div>
    )
}
