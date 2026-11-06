import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton, LemonInput, LemonSegmentedButton, LemonSelect, LemonTable } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'

import type { SmtpActivityEntryApi } from 'products/messaging/frontend/generated/api.schemas'

import { smtpSetupLogic } from './smtpSetupLogic'
import { SMTP_SNIPPETS, SmtpSnippetKey } from './smtpSnippets'

const SNIPPET_OPTIONS: { value: SmtpSnippetKey; label: string }[] = [
    { value: 'env', label: 'Settings' },
    { value: 'nodemailer', label: 'Nodemailer' },
    { value: 'django', label: 'Django' },
    { value: 'laravel', label: 'Laravel' },
]

function summarizeRecipients(recipients: string[]): string {
    return recipients.length > 2
        ? `${recipients.slice(0, 2).join(', ')} and ${recipients.length - 2} more`
        : recipients.join(', ')
}

function DetailRow({ label, value, hint }: { label: string; value: string; hint?: string }): JSX.Element {
    return (
        <div className="grid grid-cols-[6rem_1fr] gap-2 items-baseline py-1">
            <span className="font-semibold">{label}</span>
            <div className="min-w-0">
                <CopyToClipboardInline description={label.toLowerCase()} explicitValue={value}>
                    <code className="break-all">{value}</code>
                </CopyToClipboardInline>
                {hint ? <div className="text-secondary text-xs mt-0.5">{hint}</div> : null}
            </div>
        </div>
    )
}

export function SmtpSetup(): JSX.Element {
    const {
        setup,
        setupLoading,
        createdKey,
        createdKeyLoading,
        password,
        senderAddresses,
        integrationsLoading,
        integrations,
        testFrom,
        testTo,
        testResult,
        testResultLoading,
        testDisabledReason,
    } = useValues(smtpSetupLogic)
    const { createKey, setPassword, setFrom, setTo, sendTest, loadSetup } = useActions(smtpSetupLogic)
    const [snippet, setSnippet] = useState<SmtpSnippetKey>('env')

    if (setup === null) {
        return setupLoading ? (
            <Spinner className="text-lg" />
        ) : (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadSetup }}>
                Couldn't load the SMTP settings.
            </LemonBanner>
        )
    }
    if (!setup.host) {
        return <LemonBanner type="info">This PostHog instance doesn't run an SMTP relay.</LemonBanner>
    }

    const usualPorts = setup.ports.filter((port) => !port.alternate).map((port) => port.port)
    const alternatePorts = setup.ports.filter((port) => port.alternate).map((port) => port.port)
    const hasNoSender = integrations !== null && senderAddresses.length === 0

    return (
        <div className="flex flex-col gap-6 max-w-200" data-attr="smtp-setup">
            <p className="m-0 text-secondary">
                Point any app that sends email over SMTP at PostHog. These emails appear in the{' '}
                <Link to={urls.transactionalLog()}>log</Link> and follow your suppression list and sending limits.
            </p>

            {hasNoSender ? (
                <LemonBanner
                    type="warning"
                    action={{ children: 'Set up a sending domain', to: urls.transactional('channels') }}
                >
                    Emails send from a verified domain, and this project doesn't have one yet.
                </LemonBanner>
            ) : null}

            <section>
                <h3 className="mb-2">Connection details</h3>
                <DetailRow label="Host" value={setup.host} />
                <DetailRow
                    label="Port"
                    value={String(usualPorts[0])}
                    hint={`Or ${usualPorts[1]}. TLS and STARTTLS both work on every port. If your host blocks these ports, use ${alternatePorts.join(' or ')}.`}
                />
                <DetailRow
                    label="Username"
                    value={setup.username}
                    hint="Any username works, for tools that need another one."
                />
                <div className="grid grid-cols-[6rem_1fr] gap-2 items-baseline py-1">
                    <span className="font-semibold">Password</span>
                    <div className="flex flex-col gap-1 items-start min-w-0">
                        <span>A project secret key that can send email.</span>
                        {createdKey ? (
                            <LemonBanner type="success" className="w-full">
                                <div className="flex flex-col gap-1">
                                    <span>Copy this key now. You won't see it again.</span>
                                    <CopyToClipboardInline description="key" explicitValue={createdKey}>
                                        <code className="break-all">{createdKey}</code>
                                    </CopyToClipboardInline>
                                </div>
                            </LemonBanner>
                        ) : (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={createKey}
                                loading={createdKeyLoading}
                                data-attr="smtp-create-key"
                            >
                                Create a key
                            </LemonButton>
                        )}
                        <span className="text-secondary text-xs">
                            The key can only send email. Manage your keys in{' '}
                            <Link to={urls.settings('environment-secret-api-keys')}>project settings</Link>.
                        </span>
                    </div>
                </div>
            </section>

            <section className="flex flex-col gap-3">
                <h3 className="m-0">Send a test</h3>
                <div className="grid gap-3 @lg:grid-cols-2">
                    <LemonField.Pure label="From">
                        <LemonSelect
                            fullWidth
                            value={testFrom || null}
                            options={senderAddresses.map((address: string) => ({ value: address, label: address }))}
                            onChange={(value) => value && setFrom(value)}
                            loading={integrationsLoading}
                            placeholder="No verified sender"
                            data-attr="smtp-test-from"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="To">
                        <LemonInput value={testTo} onChange={setTo} type="email" data-attr="smtp-test-to" />
                    </LemonField.Pure>
                </div>
                <LemonField.Pure label="Password" info="PostHog uses it for this test and doesn't store it.">
                    <LemonInput
                        value={password}
                        onChange={setPassword}
                        type="password"
                        placeholder="phs_..."
                        data-attr="smtp-test-password"
                    />
                </LemonField.Pure>
                <div>
                    <LemonButton
                        type="secondary"
                        onClick={sendTest}
                        loading={testResultLoading}
                        disabledReason={testDisabledReason}
                        data-attr="smtp-send-test"
                    >
                        Send test email
                    </LemonButton>
                </div>
                {testResult ? (
                    <LemonBanner
                        type={testResult.ok ? 'success' : 'error'}
                        action={testResult.ok ? { children: 'Open the log', to: urls.transactionalLog() } : undefined}
                    >
                        {testResult.reply}
                    </LemonBanner>
                ) : null}
            </section>

            <section className="flex flex-col gap-2">
                <h3 className="m-0">Use it in your app</h3>
                <LemonSegmentedButton size="small" value={snippet} onChange={setSnippet} options={SNIPPET_OPTIONS} />
                <CodeSnippet language={SMTP_SNIPPETS[snippet].language ?? Language.Bash} thing="settings">
                    {SMTP_SNIPPETS[snippet].code(
                        setup.host,
                        password && createdKey ? createdKey : 'YOUR_PROJECT_SECRET_KEY'
                    )}
                </CodeSnippet>
                <ul className="list-disc pl-4 text-secondary m-0">
                    <li>
                        Opens and clicks aren't tracked, so single-use links stay intact. Add the header{' '}
                        <code>X-PostHog-Capture-Engagement: true</code> to track them.
                    </li>
                    <li>Each address in To gets its own email, so recipients can't see each other.</li>
                    <li>Attachments can be up to 10 MB in total.</li>
                    <li>A successful reply means PostHog queued the email. Delivery shows in the log.</li>
                </ul>
            </section>

            <section className="flex flex-col gap-2">
                <h3 className="m-0">Recent problems</h3>
                <LemonTable<SmtpActivityEntryApi>
                    dataSource={setup.activity}
                    size="small"
                    pagination={{ pageSize: 10 }}
                    emptyState="No problems in the last 7 days."
                    columns={[
                        {
                            title: 'Time',
                            render: (_, entry) => <TZLabel time={dayjs.unix(entry.at)} />,
                        },
                        {
                            title: 'From',
                            render: (_, entry) => entry.from ?? '',
                        },
                        {
                            title: 'To',
                            render: (_, entry) => summarizeRecipients(entry.to ?? []),
                        },
                        {
                            title: 'What happened',
                            render: (_, entry) =>
                                entry.kind === 'dropped_headers'
                                    ? `Sent without these headers: ${(entry.dropped_headers ?? []).join(', ')}`
                                    : entry.reply,
                        },
                    ]}
                />
            </section>
        </div>
    )
}
