import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { ReceivedEmailDetailApi } from 'products/workflows/frontend/generated/api.schemas'

import { VERDICT_LABEL, formatBytes, verdictTagType } from './receivedEmailLabels'

function Row({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex justify-between items-baseline gap-4 text-sm min-w-0">
            <dt className="text-secondary shrink-0">{label}</dt>
            <dd className="m-0 min-w-0 text-right break-words">{children}</dd>
        </div>
    )
}

function Verdict({ label, verdict }: { label: string; verdict: string }): JSX.Element {
    return (
        <Row label={label}>
            <LemonTag type={verdictTagType(verdict)}>{VERDICT_LABEL[verdict] ?? 'Not checked'}</LemonTag>
        </Row>
    )
}

export function ReceivedEmailDetails({ email }: { email: ReceivedEmailDetailApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <section className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                <h3 className="text-sm font-semibold m-0">Linked to</h3>
                <dl className="flex flex-col gap-2 m-0">
                    <Row label="Person">
                        {email.person ? (
                            <Link
                                to={urls.personByDistinctId(email.person.distinct_id)}
                                className="ph-no-capture"
                                data-attr="received-email-person-link"
                            >
                                View person
                            </Link>
                        ) : (
                            <Tooltip
                                title={
                                    email.sender_verified
                                        ? 'No person in this project has this email address.'
                                        : "We only link a person when the sender is verified, so a forged address can't attach to someone else."
                                }
                            >
                                <span className="text-secondary">None</span>
                            </Tooltip>
                        )}
                    </Row>
                    <Row label="Answers">
                        {email.original_send ? (
                            <Link
                                to={urls.transactionalEmailLogEntry(email.original_send.message_id)}
                                data-attr="received-email-original-send-link"
                            >
                                View original email
                            </Link>
                        ) : (
                            <Tooltip title="A reply to one of your transactional emails links back to the email it answers.">
                                <span className="text-secondary">None</span>
                            </Tooltip>
                        )}
                    </Row>
                </dl>
            </section>
            <section className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                <h3 className="text-sm font-semibold m-0">Checks</h3>
                <dl className="flex flex-col gap-2 m-0">
                    <Verdict label="SPF" verdict={email.authentication.spf} />
                    <Verdict label="DKIM" verdict={email.authentication.dkim} />
                    <Verdict label="DMARC" verdict={email.authentication.dmarc} />
                    <Verdict label="Spam scan" verdict={email.verdicts.spam} />
                    <Verdict label="Virus scan" verdict={email.verdicts.virus} />
                </dl>
            </section>
            <section className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                <h3 className="text-sm font-semibold m-0">Details</h3>
                <dl className="flex flex-col gap-2 m-0">
                    <Row label="Received">
                        <TZLabel time={email.received_at} />
                    </Row>
                    <Row label="Size">{formatBytes(email.size_bytes)}</Row>
                    <Row label="Return path">
                        <span className="ph-no-capture break-all">{email.envelope_from || '(none)'}</span>
                    </Row>
                    <div className="flex flex-col gap-0.5 text-sm">
                        <dt className="text-secondary">ID</dt>
                        <dd className="m-0">
                            <CopyToClipboardInline
                                description="received email ID"
                                selectable
                                className="font-mono text-xs break-all"
                            >
                                {email.id}
                            </CopyToClipboardInline>
                        </dd>
                    </div>
                    {email.message_id && (
                        <div className="flex flex-col gap-0.5 text-sm">
                            <dt className="text-secondary">Message-ID</dt>
                            <dd className="m-0">
                                <CopyToClipboardInline
                                    description="Message-ID"
                                    selectable
                                    className="ph-no-capture font-mono text-xs break-all"
                                >
                                    {email.message_id}
                                </CopyToClipboardInline>
                            </dd>
                        </div>
                    )}
                </dl>
            </section>
        </div>
    )
}
