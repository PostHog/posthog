import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCheckCircle, IconCopy, IconQuestion, IconRefresh, IconWarning } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    Spinner,
    Tooltip,
    lemonToast,
} from '@posthog/lemon-ui'

import { DomainConnectBanner } from 'lib/components/DomainConnect'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DnsRecord, EmailSetupModalLogicProps, emailSetupModalLogic } from './emailSetupModalLogic'

export const EmailSetupModal = (props: EmailSetupModalLogicProps): JSX.Element => {
    const logic = emailSetupModalLogic(props)
    const {
        savedIntegration,
        verificationLoading,
        isEmailSenderSubmitting,
        dnsRecords,
        domain,
        isDomainVerified,
        emailSender,
        verification,
    } = useValues(logic)
    const { verifyDomain, submitEmailSender } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)

    const emailDomain = savedIntegration?.config?.domain || ''
    const isSmtp = emailSender.provider === 'smtp'
    const busyReason = verificationLoading || isEmailSenderSubmitting ? 'Creating sender...' : undefined

    const providerOptions = [
        { value: 'ses' as const, label: 'PostHog (recommended)' },
        ...(featureFlags[FEATURE_FLAGS.MESSAGING_CUSTOM_SMTP]
            ? [{ value: 'smtp' as const, label: 'Custom SMTP' }]
            : []),
        ...(featureFlags[FEATURE_FLAGS.MESSAGING_SES] ? [{ value: 'maildev' as const, label: 'Maildev (dev)' }] : []),
    ]

    return (
        <>
            <LemonModal title="Configure email sender" width="auto" onClose={props.onClose}>
                <Form logic={emailSetupModalLogic} props={props} formKey="emailSender">
                    <div className="space-y-4">
                        {providerOptions.length > 1 && (
                            <LemonField name="provider" label="Provider">
                                <LemonSelect
                                    options={providerOptions}
                                    disabledReason={
                                        savedIntegration ? 'You cannot change the provider after creation' : busyReason
                                    }
                                />
                            </LemonField>
                        )}
                        <LemonField name="name" label="Name">
                            <LemonInput type="text" placeholder="John Doe" disabledReason={busyReason} />
                        </LemonField>
                        <LemonField name="email" label="Email address">
                            <LemonInput
                                type="text"
                                placeholder="example@example.com"
                                disabledReason={
                                    savedIntegration ? 'You cannot change the email after creation' : busyReason
                                }
                            />
                        </LemonField>
                        {isSmtp ? (
                            <>
                                <div className="flex gap-2">
                                    <LemonField name="host" label="SMTP host" className="flex-1">
                                        <LemonInput
                                            type="text"
                                            placeholder="smtp.example.com"
                                            disabledReason={busyReason}
                                        />
                                    </LemonField>
                                    <LemonField name="port" label="Port">
                                        <LemonSelect
                                            options={[
                                                { value: 587, label: '587' },
                                                { value: 465, label: '465' },
                                                { value: 2525, label: '2525' },
                                            ]}
                                            disabledReason={busyReason}
                                        />
                                    </LemonField>
                                    <LemonField name="encryption" label="Encryption">
                                        <LemonSelect
                                            options={[
                                                { value: 'starttls' as const, label: 'STARTTLS' },
                                                { value: 'ssl' as const, label: 'SSL/TLS' },
                                                { value: 'none' as const, label: 'None (dev only)' },
                                            ]}
                                            disabledReason={busyReason}
                                        />
                                    </LemonField>
                                </div>
                                <LemonField
                                    name="username"
                                    label="Username"
                                    help={
                                        savedIntegration
                                            ? 'Leave blank to keep the existing username.'
                                            : 'Your provider may call this an API key.'
                                    }
                                >
                                    <LemonInput type="text" placeholder="apikey" disabledReason={busyReason} />
                                </LemonField>
                                <LemonField
                                    name="password"
                                    label="Password"
                                    help={
                                        savedIntegration
                                            ? 'Leave blank to keep the existing password.'
                                            : 'Stored encrypted. Your provider may call this an API key.'
                                    }
                                >
                                    <LemonInput type="password" disabledReason={busyReason} />
                                </LemonField>
                            </>
                        ) : (
                            <LemonField
                                name="mail_from_subdomain"
                                label="MAIL FROM subdomain"
                                help="The subdomain used for your emails' Return-Path header. Setting a MAIL FROM domain helps improve email deliverability."
                            >
                                <LemonInput
                                    className="w-fit"
                                    type="text"
                                    placeholder="feedback"
                                    suffix={<>.{domain || 'yourdomain.com'}</>}
                                    disabledReason={busyReason}
                                />
                            </LemonField>
                        )}
                        {(!savedIntegration || isSmtp) && (
                            <div className="flex justify-end">
                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    loading={verificationLoading || isEmailSenderSubmitting}
                                    onClick={submitEmailSender}
                                >
                                    {savedIntegration ? 'Save & test connection' : 'Continue'}
                                </LemonButton>
                            </div>
                        )}
                    </div>
                </Form>

                {savedIntegration && isSmtp && (
                    <div className="mt-8 space-y-2 w-full">
                        <h2>Connection</h2>
                        {verificationLoading ? (
                            <LemonBanner type="info">
                                <div className="flex gap-2 items-center">
                                    <Spinner /> Testing the connection to your SMTP server...
                                </div>
                            </LemonBanner>
                        ) : isDomainVerified ? (
                            <LemonBanner type="success">
                                Connection verified. This sender is ready to use in workflows.
                            </LemonBanner>
                        ) : (
                            <LemonBanner type="error">
                                {verification?.error ||
                                    'The connection could not be verified. Check the host, port and credentials, then test again.'}
                            </LemonBanner>
                        )}
                        <div className="flex gap-2 justify-end">
                            <LemonButton
                                type="secondary"
                                onClick={verifyDomain}
                                disabledReason={verificationLoading ? 'Testing...' : undefined}
                                loading={verificationLoading}
                                icon={<IconRefresh />}
                            >
                                Test connection
                            </LemonButton>
                            <LemonButton type="primary" onClick={() => props.onComplete(savedIntegration?.id)}>
                                Done
                            </LemonButton>
                        </div>
                    </div>
                )}

                {savedIntegration && !isSmtp && (
                    <div className="mt-8 space-y-2 w-full">
                        <h2>DNS records</h2>
                        <p className="text-sm text-muted">
                            These DNS records are required to verify ownership of your domain. They also ensure your
                            emails are delivered to inboxes and not marked as spam.
                        </p>
                        <p className="mb-2 font-semibold">
                            Note: It can take up to 48 hours for DNS changes to propagate.
                        </p>

                        {!isDomainVerified && emailDomain && (
                            <DomainConnectBanner
                                logicKey={`email-${savedIntegration.id}`}
                                domain={emailDomain}
                                context="email"
                                integrationId={savedIntegration.id}
                                className="mb-2"
                            />
                        )}

                        <div className="overflow-x-auto">
                            <table className="w-full border-collapse">
                                <thead>
                                    <tr className="border-b">
                                        <th className="py-2 text-left">Type</th>
                                        <th className="py-2 text-left">Name</th>
                                        <th className="py-2 text-left">Value</th>
                                        <th className="py-2 text-left">Status</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {dnsRecords?.map((record: DnsRecord, index: number) => {
                                        const { subdomain, rootDomain: rootDomainSuffix } = record.parsedHostname

                                        return (
                                            <tr key={index} className="border-b">
                                                <td className="py-2 max-w-[3rem]">{record.recordType}</td>
                                                <td className="py-2 max-w-[20rem]">
                                                    <div className="flex gap-0 items-center break-all text-wrap">
                                                        <div className="flex gap-0 items-center bg-bg-light border border-border rounded px-1.5 py-0.5">
                                                            <span className="font-mono text-sm">{subdomain}</span>
                                                            {subdomain !== '@' && (
                                                                <LemonButton
                                                                    size="small"
                                                                    icon={<IconCopy />}
                                                                    onClick={() => {
                                                                        void navigator.clipboard.writeText(subdomain)
                                                                        lemonToast.success('Target copied to clipboard')
                                                                    }}
                                                                    tooltip="Copy target"
                                                                    className="ml-0.5 -mr-0.5"
                                                                />
                                                            )}
                                                        </div>
                                                        {rootDomainSuffix && (
                                                            <span className="text-muted font-mono text-sm ml-1">
                                                                {rootDomainSuffix}
                                                            </span>
                                                        )}
                                                    </div>
                                                </td>
                                                <td className="py-2 max-w-[8rem]">
                                                    <div className="flex gap-1 justify-between items-center break-all text-wrap">
                                                        <div className="flex flex-col gap-1">
                                                            <span>{record.recordValue}</span>
                                                            {record.priority != null && (
                                                                <span className="text-muted text-xs">
                                                                    Priority: {record.priority}
                                                                </span>
                                                            )}
                                                        </div>
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
                                                <td className="py-2 w-[8rem]">
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
                                        )
                                    })}
                                </tbody>
                            </table>
                            {verificationLoading && dnsRecords.length === 0 && (
                                <div className="flex flex-col gap-2 py-2">
                                    <LemonSkeleton className="h-12" />
                                    <LemonSkeleton className="h-12" />
                                    <LemonSkeleton className="h-12" />
                                </div>
                            )}
                        </div>
                        <div className="flex gap-2 justify-end">
                            <LemonButton
                                type="secondary"
                                onClick={verifyDomain}
                                disabledReason={verificationLoading ? 'Verifying...' : undefined}
                                loading={verificationLoading}
                                icon={<IconRefresh />}
                            >
                                Re-check DNS records
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={async () => {
                                    await submitEmailSender()
                                    props.onComplete(savedIntegration?.id)
                                }}
                                tooltip="You will not be able to send emails until you verify the DNS records"
                            >
                                {isDomainVerified ? 'Save' : 'Save & finish later'}
                            </LemonButton>
                        </div>
                    </div>
                )}
            </LemonModal>
        </>
    )
}
