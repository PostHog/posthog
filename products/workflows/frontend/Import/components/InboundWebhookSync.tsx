import { useActions, useValues } from 'kea'

import { IconCopy, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { customerIOImportLogic } from '../customerIOImportLogic'

export function InboundWebhookSync(): JSX.Element {
    const { syncConfig, webhookUrl, webhookSigningSecret, isSavingWebhook, webhookError, isRemovingWebhookConfig } =
        useValues(customerIOImportLogic)
    const { setWebhookSigningSecret, saveWebhookConfig, toggleWebhook, removeWebhookConfig } =
        useActions(customerIOImportLogic)

    const webhookEnabled = syncConfig?.webhook_enabled ?? false
    const hasSecret = syncConfig?.has_webhook_secret ?? false

    return (
        <div className="space-y-4">
            <p className="text-sm text-muted">
                Configure Customer.io to send a webhook when a user unsubscribes, so PostHog automatically records the
                opt-out.
            </p>

            {/* Webhook URL */}
            <div className="space-y-2">
                <label className="LemonLabel">Webhook URL</label>
                <div className="flex items-center gap-2">
                    <LemonInput
                        value={webhookUrl}
                        disabledReason="Copy this URL"
                        className="flex-1 font-mono text-xs"
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconCopy />}
                        tooltip="Copy URL"
                        onClick={() => void copyToClipboard(webhookUrl, 'webhook URL')}
                    />
                </div>
                <p className="text-xs text-muted-alt">
                    Paste this URL into Customer.io under Integrations → Add integration → Reporting webhook.
                </p>
            </div>

            {webhookError && (
                <LemonBanner type="error" className="text-sm">
                    {webhookError}
                </LemonBanner>
            )}

            {webhookEnabled && <LemonBanner type="success">Inbound webhook sync is active.</LemonBanner>}

            {/* Signing secret */}
            {hasSecret ? (
                <>
                    <div className="space-y-2">
                        <label className="LemonLabel">Webhook signing secret</label>
                        <LemonInput
                            value="••••••••••••••••"
                            disabledReason="Can't be changed"
                            suffix={
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    status="danger"
                                    tooltip="Remove signing secret"
                                    onClick={removeWebhookConfig}
                                    data-attr="customerio-webhook-sync-remove"
                                    loading={isRemovingWebhookConfig}
                                    icon={<IconTrash className="text-danger" />}
                                />
                            }
                        />
                    </div>
                    <div className="flex justify-end">
                        {webhookEnabled ? (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                onClick={() => toggleWebhook(false)}
                                data-attr="customerio-webhook-sync-disable"
                                loading={isSavingWebhook}
                            >
                                Disable sync
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="primary"
                                onClick={() => toggleWebhook(true)}
                                data-attr="customerio-webhook-sync-enable"
                                loading={isSavingWebhook}
                            >
                                Enable sync
                            </LemonButton>
                        )}
                    </div>
                </>
            ) : (
                <div className="space-y-3">
                    <div className="space-y-2">
                        <label className="LemonLabel">Webhook signing secret</label>
                        <LemonInput
                            value={webhookSigningSecret}
                            onChange={setWebhookSigningSecret}
                            placeholder="Enter your webhook signing secret"
                            type="password"
                            autoComplete="off"
                        />
                        <p className="text-xs text-muted-alt">
                            Find this in Customer.io under Settings → Webhooks → Reporting webhooks → Signing secret.
                        </p>
                    </div>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            onClick={saveWebhookConfig}
                            data-attr="customerio-webhook-sync-save"
                            loading={isSavingWebhook}
                            disabledReason={!webhookSigningSecret ? 'Enter the signing secret' : undefined}
                        >
                            Enable sync
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
