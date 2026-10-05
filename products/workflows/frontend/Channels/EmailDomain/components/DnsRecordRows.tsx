import clsx from 'clsx'
import posthog from 'posthog-js'

import { IconCheck, IconCopy, IconHourglass, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag, lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import type {
    EmailDomainSetupRecordKindEnumApi,
    EmailDomainStatusRecordApi,
} from 'products/integrations/frontend/generated/api.schemas'

export const RECORD_KIND_LABEL: Record<EmailDomainSetupRecordKindEnumApi, string> = {
    verification: 'Proves you own the domain',
    dkim: 'Signs your emails (DKIM)',
    spf: 'Lists who may send for you (SPF)',
    mail_from_mx: 'Routes bounces back to you (MAIL FROM)',
    mail_from_spf: 'Lists who may send bounces (MAIL FROM SPF)',
    dmarc: 'Tells inboxes what to do with fakes (DMARC)',
}

const RECORD_KIND_HINT: Partial<Record<EmailDomainSetupRecordKindEnumApi, string>> = {
    spf: 'Already have an SPF record at this name? Add include:amazonses.com to it instead of adding a second one.',
    mail_from_spf:
        'Already have an SPF record at this name? Add include:amazonses.com to it instead of adding a second one.',
    dmarc: 'Already have a DMARC record? Keep yours and skip this one.',
}

type RowStatus = EmailDomainStatusRecordApi['status'] | 'missing'

const ROW_STATUS: Record<RowStatus, { label: string; icon: JSX.Element; className: string }> = {
    pending: { label: 'Not found yet', icon: <IconHourglass />, className: 'text-secondary' },
    found: { label: 'Found', icon: <IconCheck />, className: 'text-success' },
    verified: { label: 'Verified', icon: <IconCheck />, className: 'text-success' },
    missing: { label: 'Missing', icon: <IconWarning />, className: 'text-danger' },
}

function CopyField({
    label,
    value,
    record,
}: {
    label: string
    value: string
    record: EmailDomainStatusRecordApi
}): JSX.Element {
    const copy = async (): Promise<void> => {
        if (await copyToClipboard(value, label, { silent: true })) {
            // pinned: analytics event name
            posthog.capture('email domain records copied', { kind: record.kind, field: label.toLowerCase() })
            lemonToast.success(`Copied the ${label.toLowerCase()}`)
        }
    }
    return (
        <div className="flex flex-col gap-0.5 min-w-0">
            <span className="text-xs text-secondary">{label}</span>
            <div className="flex items-start gap-1">
                <code className="font-mono text-xs break-all bg-fill-primary border rounded px-1.5 py-1 flex-1 min-w-0">
                    {value}
                </code>
                <LemonButton
                    size="xsmall"
                    icon={<IconCopy />}
                    tooltip={`Copy ${label.toLowerCase()}`}
                    onClick={() => void copy()}
                    data-attr="email-domain-copy-record"
                />
            </div>
        </div>
    )
}

export function DnsRecordRows({
    records,
    missing,
    showStatus,
}: {
    records: EmailDomainStatusRecordApi[]
    missing?: EmailDomainStatusRecordApi[]
    showStatus: boolean
}): JSX.Element {
    const rowStatus = (record: EmailDomainStatusRecordApi): RowStatus =>
        missing?.includes(record) ? 'missing' : record.status
    const ordered = missing?.length ? [...missing, ...records.filter((record) => !missing.includes(record))] : records
    return (
        <ol className="m-0 p-0 list-none flex flex-col gap-2" aria-label="Settings to add">
            {ordered.map((record, index) => {
                const status = ROW_STATUS[rowStatus(record)]
                const isMissing = rowStatus(record) === 'missing'
                const hint = isMissing || record.status === 'pending' ? RECORD_KIND_HINT[record.kind] : undefined
                return (
                    <li
                        key={`${record.type}-${record.hostname}-${index}`}
                        className={clsx(
                            'rounded border bg-surface-primary p-3 flex flex-col gap-2',
                            isMissing && 'border-danger bg-danger-highlight'
                        )}
                    >
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonTag type="default" className="font-mono">
                                {record.type}
                            </LemonTag>
                            <span className="text-sm font-medium">{RECORD_KIND_LABEL[record.kind]}</span>
                            {showStatus && (
                                <span
                                    className={clsx(
                                        'ml-auto inline-flex items-center gap-1 text-xs whitespace-nowrap',
                                        status.className
                                    )}
                                >
                                    {status.icon}
                                    {status.label}
                                </span>
                            )}
                        </div>
                        <div className="grid gap-2 @lg:grid-cols-2">
                            <CopyField label="Name" value={record.hostname} record={record} />
                            <CopyField
                                label={record.priority != null ? `Value (priority ${record.priority})` : 'Value'}
                                value={record.value}
                                record={record}
                            />
                        </div>
                        {hint && <p className="m-0 text-xs text-secondary">{hint}</p>}
                    </li>
                )
            })}
        </ol>
    )
}
