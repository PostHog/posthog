import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonFormDialogProps } from 'lib/lemon-ui/LemonDialog/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { DnsRecord, emailSetupModalLogic } from './emailSetupModalLogic'

interface EmailSetupModalProps {
    onComplete?: (domain: string) => void
}

const EmailSetupModalContent = ({ isLoading }: { isLoading: boolean }): JSX.Element => {
    const { emailIntegration, dnsRecords, setupResponseLoading, verificationResponseLoading } =
        useValues(emailSetupModalLogic)
    const { verifyDomain } = useActions(emailSetupModalLogic)

    if (!emailIntegration.domain) {
        return (
            <div className="space-y-4">
                <Form logic={emailSetupModalLogic} formKey="emailIntegration">
                    <LemonField name="domain" label="Domain">
                        <LemonInput
                            type="text"
                            placeholder="example.com"
                            disabled={isLoading || setupResponseLoading}
                        />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            disabled={isLoading || setupResponseLoading}
                            loading={setupResponseLoading}
                        >
                            Continue
                        </LemonButton>
                    </div>
                </Form>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <h3 className="font-semibold">Add the following DNS records to your domain</h3>
            <p className="text-sm text-muted">
                Add these DNS records to your domain's DNS configuration. Once you've added them, click the "Verify DNS
                Records" button to check if they're properly configured.
            </p>
            <div className="overflow-x-auto">
                <table className="w-full border-collapse">
                    <thead>
                        <tr className="border-b">
                            <th className="py-2 text-left">Type</th>
                            <th className="py-2 text-left">Name</th>
                            <th className="py-2 text-left">Value</th>
                        </tr>
                    </thead>
                    <tbody>
                        {dnsRecords.map((record: DnsRecord, index: number) => (
                            <tr key={index} className="border-b">
                                <td className="py-2">{record.type}</td>
                                <td className="py-2">{record.name}</td>
                                <td className="py-2 truncate max-w-[250px]">{record.value}</td>
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
                    Verify DNS Records
                </LemonButton>
            </div>
        </div>
    )
}

export const getEmailSetupModal = ({ onComplete }: EmailSetupModalProps): LemonFormDialogProps => {
    return {
        title: `Configure email sender domain`,
        description: (
            <>
                Enter the domain you'd like to send emails from. We'll help you verify ownership so that your messages
                get delivered to your users' inboxes and don't end up in spam.
            </>
        ),
        width: '30rem',
        initialValues: {},
        content: EmailSetupModalContent,
        onSubmit: async ({ domain }) => {
            try {
                onComplete?.(domain)
            } catch (error) {
                lemonToast.error('Failed to create email sender domain')
                console.error(error)
            }
        },
    }
}
