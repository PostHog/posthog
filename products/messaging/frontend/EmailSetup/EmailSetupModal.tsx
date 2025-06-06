import { IconCheckCircle, IconCopy, IconWarning } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, lemonToast, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { DnsRecord, emailSetupModalLogic, EmailSetupModalLogicProps } from './emailSetupModalLogic'

export const EmailSetupModal = (props: EmailSetupModalLogicProps): JSX.Element => {
    const { integration, integrationLoading, verification, verificationLoading } = useValues(
        emailSetupModalLogic(props)
    )
    const { verifyDomain, submitEmailSender } = useActions(emailSetupModalLogic(props))

    let modalContent = <></>

    if (!integration) {
        modalContent = (
            <Form logic={emailSetupModalLogic} formKey="emailSender">
                <div className="space-y-4">
                    <LemonField name="domain" label="Domain">
                        <LemonInput type="text" placeholder="example.com" disabled={integrationLoading} />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            disabledReason={integrationLoading ? 'Creating sender domain...' : undefined}
                            loading={integrationLoading}
                            onClick={submitEmailSender}
                        >
                            Continue
                        </LemonButton>
                    </div>
                </div>
            </Form>
        )
    } else {
        modalContent = (
            <div className="space-y-2 max-w-[60rem]">
                <p className="text-sm text-muted">
                    These DNS records verify ownership of your domain. This ensures your emails are delivered to inboxes
                    and not marked as spam.
                </p>
                <p className="font-semibold mb-2">Note: It can take up to 48 hours for DNS changes to propagate.</p>
                <div className="overflow-x-auto">
                    <table className="w-full border-collapse">
                        <thead>
                            <tr className="border-b">
                                <th className="py-2 text-left">Type</th>
                                <th className="py-2 text-left">Hostname</th>
                                <th className="py-2 text-left">Value</th>
                                <th className="py-2 text-left">Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {verification?.dnsRecords?.map((record: DnsRecord, index: number) => (
                                <tr key={index} className="border-b">
                                    <td className="py-2">{record.recordType}</td>
                                    <td className="py-2 max-w-[8rem]">
                                        <div className="flex items-center gap-1 text-wrap break-all justify-between">
                                            <span>{record.recordHostname}</span>
                                            <LemonButton
                                                size="small"
                                                icon={<IconCopy />}
                                                onClick={() => {
                                                    void navigator.clipboard.writeText(record.recordHostname)
                                                    lemonToast.success('Hostname copied to clipboard')
                                                }}
                                                tooltip="Copy hostname"
                                            />
                                        </div>
                                    </td>
                                    <td className="py-2 max-w-[8rem]">
                                        <div className="flex items-center gap-1 text-wrap break-all justify-between">
                                            <span>{record.recordValue}</span>
                                            <LemonButton
                                                size="small"
                                                icon={<IconCopy />}
                                                onClick={() => {
                                                    void navigator.clipboard.writeText(record.recordValue)
                                                    lemonToast.success('Value copied to clipboard')
                                                }}
                                                tooltip="Copy value"
                                            />
                                        </div>
                                    </td>
                                    <td className="py-2 w-[10rem]">
                                        {verificationLoading ? (
                                            <Spinner className="text-lg" />
                                        ) : record.status === 'pending' ? (
                                            <div className="flex items-center gap-1">
                                                <IconWarning className="size-6 text-warning" /> Not present
                                            </div>
                                        ) : (
                                            <div className="flex items-center gap-1">
                                                <IconCheckCircle className="size-6 text-success" /> Verified
                                            </div>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
                <div className="flex gap-2 justify-end">
                    <LemonButton
                        type="secondary"
                        onClick={verifyDomain}
                        disabledReason={verificationLoading ? 'Verifying...' : undefined}
                        loading={verificationLoading}
                    >
                        Verify DNS records
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => props.onComplete(integration.id)}
                        tooltip="You will not be able to send emails until you verify the DNS records"
                    >
                        Finish later
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <LemonModal title="Configure email sender domain" width="auto" onClose={props.onComplete}>
            {modalContent}
        </LemonModal>
    )
}
