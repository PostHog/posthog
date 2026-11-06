import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonInputSelect } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { MessageTemplateLogicProps } from './messageTemplateLogic'
import { messageTemplateTestSendLogic } from './messageTemplateTestSendLogic'

export function TestEmailRecipientField({ logicProps }: { logicProps: MessageTemplateLogicProps }): JSX.Element {
    const logic = messageTemplateTestSendLogic(logicProps)
    const { recipientEmail, recipientSuggestions, recipientWarning, membersLoading, isSandboxSenderSelected } =
        useValues(logic)
    const { setRecipientEmail, loadAllMembers } = useActions(logic)

    return (
        <>
            {isSandboxSenderSelected ? (
                <LemonInputSelect
                    mode="single"
                    allowCustomValues
                    value={recipientEmail ? [recipientEmail] : []}
                    onChange={(values) => setRecipientEmail(values[0] ?? '')}
                    options={recipientSuggestions.map((email) => ({ key: email, label: email }))}
                    loading={membersLoading}
                    placeholder="you@example.com"
                    emptyStateComponent="Type an email address and press Enter"
                    data-attr="send-test-email-recipient"
                />
            ) : (
                <LemonInput
                    type="email"
                    value={recipientEmail}
                    onChange={setRecipientEmail}
                    placeholder="you@example.com"
                    data-attr="send-test-email-recipient"
                />
            )}
            {recipientWarning === 'unverified-self' ? (
                <LemonBanner type="warning">Verify your email address to send test emails to yourself.</LemonBanner>
            ) : recipientWarning === 'unchecked' ? (
                <LemonBanner
                    type="warning"
                    action={{ children: 'Try again', onClick: loadAllMembers, loading: membersLoading }}
                >
                    Couldn't load your organization's members, so this address can't be checked. The sandbox sender only
                    delivers to verified members.
                </LemonBanner>
            ) : recipientWarning === 'not-member' ? (
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Add your own sender',
                        to: urls.workflows('channels'),
                        targetBlank: true,
                    }}
                >
                    <span translate="no" className="break-all">
                        {recipientEmail}
                    </span>{' '}
                    isn't among the verified members you can see. The sandbox sender may not deliver to it. Add your own
                    sender to email anyone.
                </LemonBanner>
            ) : null}
        </>
    )
}
