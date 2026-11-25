import { useActions, useMountedLogic, useValues } from 'kea'

import { IconArrowLeft, IconChevronRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTag, Spinner } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { organizationLogic } from 'scenes/organizationLogic'

import type { ImportProviderOptionApi } from 'products/messaging/frontend/generated/api.schemas'

import { CustomerioImportModal } from '../Workflows/import/CustomerioImportModal'
import { CustomerIOAutomationsImportItem } from './CustomerIOAutomationsImportItem'
import { customerIOImportLogic } from './customerIOImportLogic'
import { CustomerIOImportSteps } from './CustomerIOImportSteps'
import { providerImportLogic } from './providerImportLogic'
import { ProviderImportPanel } from './ProviderImportPanel'
import { ProviderLogo } from './ProviderLogo'

const CUSTOMERIO_PROVIDER = 'customerio'
const SUMMARY_STEP_COUNT = 3

function summarizeSteps(labels: string[]): string {
    if (labels.length <= SUMMARY_STEP_COUNT + 1) {
        return labels.join(', ')
    }
    return `${labels.slice(0, SUMMARY_STEP_COUNT).join(', ')} and ${labels.length - SUMMARY_STEP_COUNT} more`
}

function ProviderOption({
    providerKey,
    label,
    summary,
    importing = false,
    onClick,
    dataAttr,
}: {
    providerKey: string
    label: string
    summary: string
    importing?: boolean
    onClick: () => void
    dataAttr: string
}): JSX.Element {
    return (
        <LemonButton type="secondary" fullWidth sideIcon={<IconChevronRight />} onClick={onClick} data-attr={dataAttr}>
            <div className="flex min-w-0 items-center gap-3 py-1 font-normal">
                <ProviderLogo providerKey={providerKey} />
                <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="flex items-center gap-2 font-semibold">
                        {label}
                        {importing && <LemonTag type="highlight">Importing</LemonTag>}
                    </span>
                    <span className="truncate text-xs text-secondary" title={summary}>
                        {summary}
                    </span>
                </div>
            </div>
        </LemonButton>
    )
}

function ProviderPicker(): JSX.Element {
    const { orderedImportProviders, latestImportRunByProvider, showsAutomationImport } = useValues(providerImportLogic)
    const { selectProvider } = useActions(providerImportLogic)

    return (
        <div className="flex flex-col gap-2">
            {orderedImportProviders.map((provider) => {
                const stepLabels = provider.steps.map((step) => step.label)
                if (provider.key === CUSTOMERIO_PROVIDER && showsAutomationImport) {
                    stepLabels.push('Automations')
                }
                return (
                    <ProviderOption
                        key={provider.key}
                        providerKey={provider.key}
                        label={provider.label}
                        summary={summarizeSteps(stepLabels)}
                        importing={['queued', 'running'].includes(latestImportRunByProvider[provider.key]?.status)}
                        onClick={() => selectProvider(provider.key)}
                        dataAttr={`import-provider-${provider.key}`}
                    />
                )
            })}
        </div>
    )
}

function SelectedProvider({ provider }: { provider: ImportProviderOptionApi }): JSX.Element {
    const { hasSeveralProviders, showsAutomationImport } = useValues(providerImportLogic)
    const { selectProvider } = useActions(providerImportLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)
    const isCustomerIO = provider.key === CUSTOMERIO_PROVIDER

    return (
        <div className="space-y-4">
            {hasSeveralProviders && (
                <LemonButton
                    size="small"
                    type="tertiary"
                    icon={<IconArrowLeft />}
                    onClick={() => selectProvider(null)}
                    data-attr="import-provider-back"
                >
                    All tools
                </LemonButton>
            )}
            {/* Only Customer.io keeps its key after the import, so only it needs an admin. The API checks workflow access for the rest. */}
            {isCustomerIO && isAdminOrOwner === false ? (
                <>
                    {/* Draft workflows store no Customer.io key, so the automation import needs no admin. */}
                    {showsAutomationImport && <CustomerIOAutomationsImportItem />}
                    <AccessDenied object="Customer.io integration" inline />
                </>
            ) : isCustomerIO ? (
                <CustomerIOImportSteps provider={provider} />
            ) : (
                <ProviderImportPanel provider={provider} pinActions />
            )}
        </div>
    )
}

function ProviderImportModalContent(): JSX.Element {
    const { selectedProvider, importProviders, importProvidersLoading } = useValues(providerImportLogic)
    const { loadImportProviders } = useActions(providerImportLogic)

    if (importProviders === null && importProvidersLoading) {
        return (
            <div className="flex justify-center py-8">
                <Spinner className="text-3xl" />
            </div>
        )
    }
    if (importProviders === null) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadImportProviders }}>
                Couldn't load what you can import.
            </LemonBanner>
        )
    }
    return selectedProvider === null ? <ProviderPicker /> : <SelectedProvider provider={selectedProvider} />
}

export function ProviderImportModal(): JSX.Element {
    useMountedLogic(customerIOImportLogic)
    const { isImportModalOpen, selectedProvider, showsAutomationImport } = useValues(providerImportLogic)
    const { closeImportModal } = useActions(providerImportLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)

    const isCustomerIO = selectedProvider?.key === CUSTOMERIO_PROVIDER
    const title = isCustomerIO
        ? 'Customer.io integration'
        : selectedProvider
          ? `Import from ${selectedProvider.label}`
          : 'Import from another tool'

    return (
        <>
            <LemonModal
                title={title}
                description={
                    isCustomerIO
                        ? showsAutomationImport
                            ? isAdminOrOwner === false
                                ? 'Import automations from Customer.io as draft workflows.'
                                : 'Import categories, unsubscribed users, suppressed addresses and automations from Customer.io.'
                            : 'Import categories, unsubscribed users and suppressed addresses from Customer.io.'
                        : selectedProvider
                          ? undefined
                          : 'Bring your data with you when you move to PostHog.'
                }
                isOpen={isImportModalOpen}
                onClose={closeImportModal}
                width={640}
            >
                <ProviderImportModalContent />
            </LemonModal>
            <CustomerioImportModal />
        </>
    )
}
