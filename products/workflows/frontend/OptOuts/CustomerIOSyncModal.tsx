import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonTag,
    Link,
    Spinner,
} from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { customerIOSyncLogic } from './customerIOSyncLogic'

export function CustomerIOSyncModal(): JSX.Element {
    const { isSyncModalOpen, status, statusLoading, statusError, isSaving } = useValues(customerIOSyncLogic)
    const { closeSyncModal, submitSyncForm } = useActions(customerIOSyncLogic)

    return (
        <LemonModal
            title="Sync unsubscribed users with Customer.io"
            description="Keep PostHog's suppression list in sync with your Customer.io workspace while email campaigns are split between both systems."
            isOpen={isSyncModalOpen}
            onClose={closeSyncModal}
            width={640}
            footer={
                <div className="flex gap-2 justify-end">
                    <LemonButton type="secondary" onClick={closeSyncModal}>
                        Close
                    </LemonButton>
                    <LemonButton type="primary" loading={isSaving} onClick={submitSyncForm}>
                        Save configuration
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                {statusLoading ? (
                    <div className="flex items-center gap-2">
                        <Spinner />
                        <span>Loading current configuration…</span>
                    </div>
                ) : statusError ? (
                    <LemonBanner type="error">{statusError}</LemonBanner>
                ) : (
                    <div className="space-y-2 text-sm">
                        <div className="flex items-center gap-2">
                            <span className="font-medium">Outbound sync (PostHog → Customer.io):</span>
                            <LemonTag type={status.outbound_enabled ? 'success' : 'muted'}>
                                {status.outbound_enabled ? 'Enabled' : 'Not configured'}
                            </LemonTag>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="font-medium">Inbound webhook (Customer.io → PostHog):</span>
                            <LemonTag type={status.webhook_configured ? 'success' : 'muted'}>
                                {status.webhook_configured ? 'Enabled' : 'Not configured'}
                            </LemonTag>
                        </div>
                    </div>
                )}

                <LemonDivider />

                <div>
                    <h4 className="font-semibold mb-2">1. Point Customer.io at PostHog</h4>
                    <p className="text-sm text-muted mb-2">
                        In Customer.io, open <b>Settings → Integrations → Reporting Webhooks</b>, create a new webhook,
                        and enable the <b>Unsubscribed</b> event. Paste the URL below as the destination, and copy the
                        signing secret Customer.io shows you into the form at the bottom of this modal.
                    </p>
                    {status.webhook_url ? (
                        <div className="flex items-center gap-2">
                            <CopyToClipboardInline description="webhook URL" iconStyle={{ color: 'var(--muted)' }}>
                                {status.webhook_url}
                            </CopyToClipboardInline>
                        </div>
                    ) : (
                        <LemonBanner type="info">
                            Save the configuration once to generate your team's webhook URL.
                        </LemonBanner>
                    )}
                </div>

                <LemonDivider />

                <div>
                    <h4 className="font-semibold mb-1">2. Outbound sync credentials</h4>
                    <p className="text-sm text-muted mb-3">
                        PostHog uses the Customer.io{' '}
                        <Link to="https://docs.customer.io/integrations/api/track/" target="_blank">
                            Track API
                        </Link>{' '}
                        to push unsubscribes. Find your Site ID and a Track API Key under{' '}
                        <b>Settings → API Credentials → Track API Keys</b> in Customer.io.
                    </p>

                    <Form logic={customerIOSyncLogic} formKey="syncForm" enableFormOnSubmit className="space-y-3">
                        <LemonField name="site_id" label="Site ID">
                            <LemonInput placeholder={status.site_id || 'cio_site_id'} />
                        </LemonField>
                        <LemonField
                            name="track_api_key"
                            label="Track API Key"
                            help="Stored encrypted. Leave blank to keep the current key."
                        >
                            <LemonInput type="password" placeholder="••••••••" />
                        </LemonField>
                        <LemonField
                            name="webhook_signing_secret"
                            label="Webhook signing secret"
                            help="The HMAC secret Customer.io shows you when creating the reporting webhook. Leave blank to keep the current secret."
                        >
                            <LemonInput type="password" placeholder="••••••••" />
                        </LemonField>
                        <LemonField name="region" label="Region">
                            <LemonSelect
                                options={[
                                    { label: 'US (api.customer.io)', value: 'us' },
                                    { label: 'EU (beta-api-eu.customer.io)', value: 'eu' },
                                ]}
                            />
                        </LemonField>
                    </Form>
                </div>
            </div>
        </LemonModal>
    )
}
