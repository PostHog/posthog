import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCheckCircle, IconCopy, IconQuestion, IconWarning } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect, Spinner, Tooltip, lemonToast } from '@posthog/lemon-ui'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { DnsRecord, EmailSetupModalLogicProps, emailSetupModalLogic } from './emailSetupModalLogic'

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
                    <FlaggedFeature flag="messaging-ses">
                        {/* NOTE: We probably dont want to actually give the options - this is just for our own testing */}
                        <LemonField name="provider" label="Provider">
                            <LemonSelect
                                options={[
                                    { value: 'ses', label: 'AWS SES' },
                                    { value: 'maildev', label: 'Maildev' },
                                ]}
                            />
                        </LemonField>
                    </FlaggedFeature>
                    <LemonField name="name" label="Name">
                        <LemonInput type="text" placeholder="John Doe" disabled={integrationLoading} />
                    </LemonField>
                    <LemonField name="email" label="Email">
                        <LemonInput type="text" placeholder="example@example.com" disabled={integrationLoading} />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            disabledReason={integrationLoading ? 'Creating sender...' : undefined}
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
                    These DNS records are required to verify ownership of your domain. They also ensure your emails are
                    delivered to inboxes and not marked as spam.
                </p>
                <p className="mb-2 font-semibold">Note: It can take up to 48 hours for DNS changes to propagate.</p>
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
                                        <div className="flex gap-1 justify-between items-center break-all text-wrap">
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
                                        <div className="flex gap-1 justify-between items-center break-all text-wrap">
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
                                            <div className="flex gap-1 items-center">
                                                <IconWarning className="size-6 text-warning" /> Not present
                                            </div>
                                        ) : record.status === 'success' ? (
                                            <div className="flex gap-1 items-center">
                                                <IconCheckCircle className="size-6 text-success" /> Verified
                                            </div>
                                        ) : (
                                            <Tooltip title="We are unable to verify this record at the moment">
                                                <div className="flex gap-1 items-center">
                                                    <IconQuestion className="size-6 text-muted" /> Unknown
                                                </div>
                                            </Tooltip>
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
        <LemonModal title="Configure email sender" width="auto" onClose={props.onComplete}>
            {modalContent}
        </LemonModal>
    )
}
