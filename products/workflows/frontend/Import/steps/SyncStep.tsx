import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { messagingTabUrl } from '../../messagingTabUrl'
import { ImportStepFooter } from '../components/ImportStepFooter'
import { InboundWebhookSync } from '../components/InboundWebhookSync'
import { OutboundTrackSync } from '../components/OutboundTrackSync'
import { customerIOImportLogic } from '../customerIOImportLogic'

function SyncStatusTag({ enabled }: { enabled: boolean }): JSX.Element {
    return enabled ? <LemonTag type="success">On</LemonTag> : <LemonTag>Off</LemonTag>
}

export function SyncStep(): JSX.Element {
    const { syncConfig } = useValues(customerIOImportLogic)
    const { location } = useValues(router)

    return (
        <div className="space-y-6">
            <p className="text-sm text-secondary m-0">
                While you still send from Customer.io, these keep opt-outs the same in both tools. Turn them off when
                you finish moving.
            </p>
            <section className="space-y-3">
                <div className="flex items-center gap-2">
                    <h3 className="text-base font-semibold m-0">Customer.io to PostHog</h3>
                    <SyncStatusTag enabled={syncConfig?.webhook_enabled ?? false} />
                </div>
                <InboundWebhookSync />
            </section>
            <section className="space-y-3 border-t pt-4">
                <div className="flex items-center gap-2">
                    <h3 className="text-base font-semibold m-0">PostHog to Customer.io</h3>
                    <SyncStatusTag enabled={syncConfig?.track_enabled ?? false} />
                </div>
                <OutboundTrackSync />
            </section>
            <ImportStepFooter>
                <LemonButton
                    type="primary"
                    to={messagingTabUrl(location.pathname, 'opt-outs')}
                    data-attr="messaging-import-view-opt-outs"
                >
                    View opt-outs
                </LemonButton>
            </ImportStepFooter>
        </div>
    )
}
