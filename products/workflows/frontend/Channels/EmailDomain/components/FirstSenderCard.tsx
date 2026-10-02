import { useActions, useValues } from 'kea'

import { IconCheck, IconSend } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { emailDomainSenderLogic } from '../emailDomainSenderLogic'

function SenderNameField(): JSX.Element {
    const { senderName, senderNameChanged, senderSaving } = useValues(emailDomainSenderLogic)
    const { setSenderName, saveSender } = useActions(emailDomainSenderLogic)
    const canSave = senderNameChanged && Boolean(senderName.trim()) && !senderSaving
    return (
        <div className="flex flex-col gap-1">
            <label className="text-sm" htmlFor="email-domain-sender-name">
                Name
            </label>
            <div className="flex gap-2">
                <LemonInput
                    id="email-domain-sender-name"
                    className="flex-1"
                    value={senderName}
                    onChange={setSenderName}
                    onPressEnter={canSave ? saveSender : undefined}
                    placeholder="Acme"
                />
                {senderNameChanged && (
                    <LemonButton
                        type="secondary"
                        onClick={saveSender}
                        loading={senderSaving}
                        disabledReason={senderSaving ? 'Saving' : !senderName.trim() ? 'Type a name' : undefined}
                        data-attr="email-domain-save-sender-name"
                    >
                        Save
                    </LemonButton>
                )}
            </div>
        </div>
    )
}

function TestEmailButton(): JSX.Element {
    const { testSendResultLoading, testEmailSent, user } = useValues(emailDomainSenderLogic)
    const { sendTestEmail } = useActions(emailDomainSenderLogic)
    return (
        <LemonButton
            type={testEmailSent ? 'secondary' : 'primary'}
            icon={testEmailSent ? <IconCheck /> : <IconSend />}
            loading={testSendResultLoading}
            disabledReason={testSendResultLoading ? 'Sending' : !user?.email ? 'Your account has no email' : undefined}
            onClick={sendTestEmail}
            tooltip={user?.email ? `Sends to ${user.email}` : undefined}
            data-attr="email-domain-send-test-email"
        >
            {testEmailSent ? 'Send another test' : 'Send me a test email'}
        </LemonButton>
    )
}

export function FirstSenderCard(): JSX.Element {
    const { senderName, fromAddress } = useValues(emailDomainSenderLogic)
    return (
        <section className="rounded-lg border bg-surface-primary p-5 flex flex-col gap-4">
            <div className="flex flex-col gap-0.5">
                <h2 className="m-0 text-lg font-semibold">Your first sender</h2>
                <p className="m-0 text-sm text-secondary">The name and address people see in their inbox.</p>
            </div>
            <div className="grid gap-3 @md:grid-cols-2">
                <SenderNameField />
                <div className="flex flex-col gap-1">
                    <label className="text-sm" htmlFor="email-domain-sender-address">
                        Address
                    </label>
                    <LemonInput
                        id="email-domain-sender-address"
                        className="font-mono"
                        value={fromAddress ?? ''}
                        disabledReason="The address is fixed. Add another sender for a different one."
                    />
                </div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 rounded bg-fill-primary border px-3 py-2">
                <span className="text-sm min-w-0 break-all">
                    <span className="font-medium">{senderName || 'Your name'}</span>{' '}
                    <span className="text-secondary font-mono">&lt;{fromAddress}&gt;</span>
                </span>
                <TestEmailButton />
            </div>
        </section>
    )
}
