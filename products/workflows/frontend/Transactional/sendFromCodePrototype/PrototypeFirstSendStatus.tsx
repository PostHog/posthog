// PROTOTYPE (ticket #320), throwaway: the page listens for the team's first send and says when it lands.
import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { useSendFromCodePrototype } from './useSendFromCodePrototype'

export function PrototypeFirstSendStatus(): JSX.Element {
    const { firstSend, set } = useSendFromCodePrototype()

    if (firstSend === 'arrived') {
        return (
            <div className="flex flex-wrap items-center gap-2 rounded border border-success bg-success-highlight px-3 py-2">
                <IconCheckCircle className="text-success text-lg" />
                <span className="flex-1 min-w-0">
                    <b>Your first email arrived.</b> PostHog delivered <code>welcome</code> to jane@example.com and
                    linked it to her person profile.
                </span>
                <LemonButton size="small" type="secondary" to={urls.transactionalLog()}>
                    Open in log
                </LemonButton>
            </div>
        )
    }
    return (
        <div className="flex flex-wrap items-center gap-2 rounded border px-3 py-2">
            <Spinner textColored />
            <span className="flex-1 min-w-0 text-secondary">
                Waiting for your first send. This updates by itself when it lands.
            </span>
            <LemonButton size="xsmall" type="tertiary" onClick={() => set({ firstSend: 'arrived' })}>
                Simulate a send
            </LemonButton>
        </div>
    )
}
