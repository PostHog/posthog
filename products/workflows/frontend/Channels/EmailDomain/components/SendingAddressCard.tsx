import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { DEFAULT_LOCAL_PART, EmailDomainWizardLogicProps, emailDomainWizardLogic } from '../emailDomainWizardLogic'

interface SendPrefixOption {
    prefix: string
    label: string
    why: string
}

const SEND_PREFIX_OPTIONS: SendPrefixOption[] = [
    { prefix: 'mail', label: 'mail.', why: 'Keeps your main domain safe if a campaign ever lands in spam.' },
    { prefix: 'send', label: 'send.', why: 'Same protection, different name.' },
    {
        prefix: '',
        label: 'No subdomain',
        why: 'Send straight from the main domain. One bad campaign can hurt your login and support emails too.',
    },
]

const CUSTOM_PREFIX = '__custom__'
const CUSTOM_PREFIX_PLACEHOLDER = 'news'
const CUSTOM_PREFIX_WHY = 'Any name works, as long as nothing else uses it yet.'

function SendPrefixPicker(props: EmailDomainWizardLogicProps): JSX.Element {
    const logic = emailDomainWizardLogic(props)
    const { selectedDomain, sendPrefix, customPrefixOpen } = useValues(logic)
    const { setSendPrefix, setCustomPrefixOpen } = useActions(logic)
    const preset = SEND_PREFIX_OPTIONS.find((option) => option.prefix === sendPrefix)
    const custom = customPrefixOpen || !preset
    const pick = (value: string): void => {
        setCustomPrefixOpen(value === CUSTOM_PREFIX)
        setSendPrefix(value === CUSTOM_PREFIX ? CUSTOM_PREFIX_PLACEHOLDER : value)
    }
    return (
        <div className="flex flex-col gap-2">
            <span className="text-sm">Sending subdomain</span>
            <LemonSegmentedButton
                size="small"
                value={custom ? CUSTOM_PREFIX : sendPrefix}
                onChange={pick}
                options={[
                    ...SEND_PREFIX_OPTIONS.map((option) => ({ value: option.prefix, label: option.label })),
                    { value: CUSTOM_PREFIX, label: 'Custom' },
                ]}
            />
            {custom && (
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonInput
                        id="email-domain-send-prefix"
                        className="w-40 font-mono"
                        value={sendPrefix}
                        onChange={setSendPrefix}
                        placeholder={CUSTOM_PREFIX_PLACEHOLDER}
                        autoFocus
                    />
                    <span className="font-mono text-secondary break-all">.{selectedDomain}</span>
                </div>
            )}
            <span className="text-sm text-secondary">{custom ? CUSTOM_PREFIX_WHY : preset.why}</span>
        </div>
    )
}

function SenderIdentityFields(props: EmailDomainWizardLogicProps): JSX.Element {
    const logic = emailDomainWizardLogic(props)
    const { senderName, suggestedSenderName, localPart, sendingDomain } = useValues(logic)
    const { setSenderNameInput, setLocalPart } = useActions(logic)
    return (
        <div className="grid grid-cols-1 @md:grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5 text-sm">
                <label htmlFor="email-domain-sender-name-input">Name</label>
                <LemonInput
                    id="email-domain-sender-name-input"
                    value={senderName}
                    onChange={setSenderNameInput}
                    placeholder={suggestedSenderName}
                />
                <span className="text-xs text-secondary">Shown as the sender in the inbox.</span>
            </div>
            <div className="flex flex-col gap-1.5 text-sm">
                <label htmlFor="email-domain-local-part">Email address</label>
                <LemonInput
                    id="email-domain-local-part"
                    className="font-mono"
                    value={localPart}
                    onChange={setLocalPart}
                    placeholder={DEFAULT_LOCAL_PART}
                    suffix={<span className="font-mono text-secondary break-all">@{sendingDomain}</span>}
                />
                <span className="text-xs text-secondary">Replies go to this address unless you set another.</span>
            </div>
        </div>
    )
}

function BouncePrefixField(props: EmailDomainWizardLogicProps): JSX.Element {
    const logic = emailDomainWizardLogic(props)
    const { bouncePrefix, advancedOpen, sendingDomain, domainSender, replyTo } = useValues(logic)
    const sharedBouncePrefix = domainSender ? (domainSender.config?.mail_from_subdomain ?? 'feedback') : null
    const { setBouncePrefix, setAdvancedOpen, setReplyTo } = useActions(logic)
    if (!advancedOpen) {
        return (
            <LemonButton
                type="tertiary"
                size="xsmall"
                className="self-start"
                onClick={() => setAdvancedOpen(true)}
                data-attr="email-domain-advanced"
            >
                Advanced
            </LemonButton>
        )
    }
    return (
        <div className="flex flex-col gap-1.5 text-sm">
            <label htmlFor="email-domain-bounce-prefix">Bounce subdomain</label>
            <div className="flex items-center gap-2 flex-wrap">
                <LemonInput
                    id="email-domain-bounce-prefix"
                    className="w-40 font-mono"
                    value={sharedBouncePrefix ?? bouncePrefix}
                    onChange={setBouncePrefix}
                    placeholder="feedback"
                    disabledReason={
                        sharedBouncePrefix !== null
                            ? 'This domain already sends email, so a new address uses its bounce subdomain.'
                            : undefined
                    }
                />
                <span className="font-mono text-secondary break-all">.{sendingDomain}</span>
            </div>
            <span className="text-xs text-secondary">Where bounced emails return to. Almost nobody changes this.</span>
            <label htmlFor="email-domain-reply-to" className="mt-3">
                Default reply-to address <span className="text-secondary">(optional)</span>
            </label>
            <LemonInput
                id="email-domain-reply-to"
                className="max-w-80"
                value={replyTo}
                onChange={setReplyTo}
                placeholder="support@example.com"
            />
            <span className="text-xs text-secondary">
                Replies go here when an email step has no reply-to address of its own. Leave empty to send replies to
                the sender address.
            </span>
        </div>
    )
}

export function SendingAddressCard(props: EmailDomainWizardLogicProps): JSX.Element {
    const { fromAddress, senderName, suggestedSenderName } = useValues(emailDomainWizardLogic(props))
    const fromName = senderName.trim() || suggestedSenderName
    return (
        <section className="rounded-lg border bg-accent-highlight-secondary p-5 flex flex-col gap-4">
            <div className="flex flex-col gap-1">
                <span className="text-sm text-secondary">Emails will come from</span>
                <span className="text-xl @md:text-2xl font-semibold break-all">
                    <span>{fromName}</span>{' '}
                    <span className="font-mono">
                        &lt;<span>{fromAddress}</span>&gt;
                    </span>
                </span>
            </div>
            <SendPrefixPicker {...props} />
            <SenderIdentityFields {...props} />
            <BouncePrefixField {...props} />
        </section>
    )
}
