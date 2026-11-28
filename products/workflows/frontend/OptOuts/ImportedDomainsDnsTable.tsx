import { useActions, useValues } from 'kea'

import { IconCopy, IconDownload, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Spinner, lemonToast } from '@posthog/lemon-ui'
import type { LemonTagType } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { downloadFile } from 'lib/utils/dom'

import type {
    EmailDomainSetupStatusEnumApi,
    EmailDomainStatusApi,
    EmailDomainStatusRecordApi,
} from 'products/integrations/frontend/generated/api.schemas'

import { ImportedDomainRecord, dnsRecordsAsText, dnsRecordsAsZoneFile } from './importedDomainRecords'
import { providerImportLogic } from './providerImportLogic'

const DOMAIN_STATUS: Record<EmailDomainSetupStatusEnumApi, { label: string; type: LemonTagType }> = {
    not_started: { label: 'Waiting for DNS records', type: 'default' },
    pending: { label: 'Waiting for DNS records', type: 'default' },
    records_found: { label: 'Records found, checking', type: 'highlight' },
    verified: { label: 'Checking', type: 'highlight' },
    temporary_failure: { label: "Can't see the records yet", type: 'warning' },
    failed: { label: 'Verification failed, check again', type: 'danger' },
}

const RECORD_STATUS: Record<EmailDomainStatusRecordApi['status'], string> = {
    pending: 'Not found yet',
    found: 'Found',
    verified: 'Verified',
}

function domainStatusTag(status: EmailDomainStatusApi | undefined): JSX.Element {
    if (!status) {
        return <LemonTag>Unknown</LemonTag>
    }
    if (status.verified) {
        return <LemonTag type="success">Verified</LemonTag>
    }
    const { label, type } = DOMAIN_STATUS[status.status]
    return <LemonTag type={type}>{label}</LemonTag>
}

export function ImportedDomainsDnsTable(): JSX.Element | null {
    const { importedDomainSenders, importedDomainStatuses, importedDomainStatusesLoading, importedDomainRecords } =
        useValues(providerImportLogic)
    const { loadImportedDomainStatuses } = useActions(providerImportLogic)

    if (importedDomainSenders.length === 0) {
        return null
    }

    const copyAll = async (): Promise<void> => {
        if (await copyToClipboard(dnsRecordsAsText(importedDomainRecords), 'DNS records', { silent: true })) {
            lemonToast.success('Copied every DNS record')
        }
    }
    const downloadZoneFile = (): void => {
        downloadFile(
            new File([dnsRecordsAsZoneFile(importedDomainRecords)], 'posthog-email-dns-records.zone', {
                type: 'text/plain',
            })
        )
    }

    return (
        <div className="space-y-2" data-attr="imported-domains-dns">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <label className="LemonLabel">Sending domains</label>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconRefresh />}
                    loading={importedDomainStatusesLoading}
                    onClick={() => loadImportedDomainStatuses(true)}
                    data-attr="imported-domains-check-again"
                >
                    Check again
                </LemonButton>
            </div>
            {importedDomainStatuses === null ? (
                <div className="flex justify-center py-4">
                    <Spinner />
                </div>
            ) : (
                <>
                    <ul className="m-0 p-0 list-none flex flex-col gap-1">
                        {importedDomainSenders.map(({ domain, integrationId }) => (
                            <li key={integrationId} className="flex items-center justify-between gap-2 text-sm">
                                <span className="font-medium break-all">{domain}</span>
                                {domainStatusTag(importedDomainStatuses?.[integrationId])}
                            </li>
                        ))}
                    </ul>
                    {importedDomainRecords.length > 0 ? (
                        <>
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <span className="text-xs text-secondary">
                                    Publish these records at your DNS host. Keep your old provider's records until
                                    nothing sends through it.
                                </span>
                                <div className="flex gap-2">
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        icon={<IconCopy />}
                                        onClick={() => void copyAll()}
                                        data-attr="imported-domains-copy-all"
                                    >
                                        Copy all
                                    </LemonButton>
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        icon={<IconDownload />}
                                        onClick={downloadZoneFile}
                                        tooltip="A BIND zone file, which most DNS hosts can import"
                                        data-attr="imported-domains-download-zone-file"
                                    >
                                        Download zone file
                                    </LemonButton>
                                </div>
                            </div>
                            <LemonTable<ImportedDomainRecord>
                                size="small"
                                dataSource={importedDomainRecords}
                                rowKey={(record) =>
                                    `${record.domain}-${record.type}-${record.hostname}-${record.value}`
                                }
                                columns={[
                                    { title: 'Domain', dataIndex: 'domain' },
                                    { title: 'Type', dataIndex: 'type' },
                                    {
                                        title: 'Name',
                                        render: (_, record) => (
                                            <code className="text-xs break-all">{record.hostname}</code>
                                        ),
                                    },
                                    {
                                        title: 'Value',
                                        render: (_, record) => (
                                            <code className="text-xs break-all">
                                                {record.priority != null ? `${record.priority} ` : ''}
                                                {record.value}
                                            </code>
                                        ),
                                    },
                                    { title: 'Status', render: (_, record) => RECORD_STATUS[record.status] },
                                ]}
                            />
                        </>
                    ) : null}
                </>
            )}
        </div>
    )
}
