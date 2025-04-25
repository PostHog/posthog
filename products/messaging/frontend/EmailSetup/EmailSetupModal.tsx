import { IconCheckCircle, IconCopy, IconWarning } from '@posthog/icons'
import { LemonButton, LemonInput, lemonToast, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonDialogProps } from 'lib/lemon-ui/LemonDialog/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { DnsRecord, emailSetupModalLogic, EmailSetupModalLogicProps } from './emailSetupModalLogic'

const EmailSetupModalContent = (props: EmailSetupModalLogicProps): JSX.Element => {
    const { setupResponse, setupResponseLoading, verificationResponseLoading } = useValues(emailSetupModalLogic(props))
    const { verifyDomain, submitEmailIntegration } = useActions(emailSetupModalLogic(props))

    if (!setupResponse) {
        return (
            <Form logic={emailSetupModalLogic} formKey="emailIntegration">
                <div className="space-y-4">
                    <LemonField name="domain" label="Domain">
                        <LemonInput type="text" placeholder="example.com" disabled={setupResponseLoading} />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            disabledReason={setupResponseLoading ? 'Creating sender domain...' : undefined}
                            loading={setupResponseLoading}
                            onClick={submitEmailIntegration}
                        >
                            Continue
                        </LemonButton>
                    </div>
                </div>
            </Form>
        )
    }

    return (
        <div className="space-y-2 max-w-[50rem]">
            <p className="text-sm text-muted">
                These DNS records verify ownership of your domain. This ensures your emails make it to your users'
                inboxes and aren't marked as spam.
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
                        {setupResponse.dnsRecords?.map((record: DnsRecord, index: number) => (
                            <tr key={index} className="border-b">
                                <td className="py-2">{record.recordType}</td>
                                <td className="py-2 max-w-[160px]">
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
                                <td className="py-2 max-w-[200px]">
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
                                <td className="py-2 w-24">
                                    {verificationResponseLoading ? (
                                        <Spinner className="text-lg" />
                                    ) : record.status === 'pending' ? (
                                        <div className="flex items-center gap-1">
                                            <IconWarning className="size-6 text-warning" /> Pending
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
            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    onClick={verifyDomain}
                    disabled={verificationResponseLoading}
                    loading={verificationResponseLoading}
                >
                    Verify DNS records
                </LemonButton>
            </div>
        </div>
    )
}

export const getEmailSetupModal = ({ onComplete }: EmailSetupModalLogicProps): LemonDialogProps => {
    return {
        title: `Configure email sender domain`,
        width: 'auto',
        content: <EmailSetupModalContent onComplete={onComplete} />,
        primaryButton: null,
        secondaryButton: null,
    }
}
