import { useActions, useMountedLogic, useValues } from 'kea'

import { IconArrowLeft, IconChevronRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTag, Spinner } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { organizationLogic } from 'scenes/organizationLogic'

import { customerIOImportLogic } from './customerIOImportLogic'
import { CustomerIOImportSteps } from './CustomerIOImportSteps'
import { providerImportLogic } from './providerImportLogic'
import { ProviderImportPanel } from './ProviderImportPanel'

const CUSTOMERIO_PROVIDER = 'customerio'

function ProviderPicker(): JSX.Element {
    const { importProviders, latestImportRunByProvider } = useValues(providerImportLogic)
    const { selectProvider } = useActions(providerImportLogic)

    return (
        <div className="flex flex-col gap-2">
            {importProviders?.map((provider) => (
                <LemonButton
                    key={provider.key}
                    type="secondary"
                    fullWidth
                    sideIcon={<IconChevronRight />}
                    onClick={() => selectProvider(provider.key)}
                    data-attr={`import-provider-${provider.key}`}
                >
                    <div className="flex flex-col gap-0.5 py-1 font-normal">
                        <span className="flex items-center gap-2 font-semibold">
                            {provider.label}
                            {['queued', 'running'].includes(latestImportRunByProvider[provider.key]?.status) && (
                                <LemonTag type="highlight">Importing</LemonTag>
                            )}
                        </span>
                        <span className="text-xs text-secondary">
                            {provider.steps.map((step) => step.label).join(', ')}
                        </span>
                    </div>
                </LemonButton>
            ))}
        </div>
    )
}

export function ProviderImportModal(): JSX.Element {
    useMountedLogic(customerIOImportLogic)
    const { isImportModalOpen, selectedProvider, hasSeveralProviders, importProviders, importProvidersLoading } =
        useValues(providerImportLogic)
    const { closeImportModal, selectProvider, loadImportProviders } = useActions(providerImportLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)

    const isCustomerIO = selectedProvider?.key === CUSTOMERIO_PROVIDER
    const title = isCustomerIO
        ? 'Customer.io integration'
        : selectedProvider
          ? `Import from ${selectedProvider.label}`
          : 'Import from another tool'

    return (
        <LemonModal
            title={title}
            description={
                isCustomerIO
                    ? 'Import categories, unsubscribed users and suppressed addresses from Customer.io.'
                    : selectedProvider
                      ? undefined
                      : 'Bring your data with you when you move to PostHog.'
            }
            isOpen={isImportModalOpen}
            onClose={closeImportModal}
            width={640}
        >
            {isAdminOrOwner === false ? (
                <AccessDenied object={isCustomerIO ? 'Customer.io integration' : 'imports'} inline />
            ) : importProviders === null && importProvidersLoading ? (
                <div className="flex justify-center py-8">
                    <Spinner className="text-3xl" />
                </div>
            ) : importProviders === null ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadImportProviders }}>
                    Couldn't load what you can import.
                </LemonBanner>
            ) : selectedProvider === null ? (
                <ProviderPicker />
            ) : (
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
                    {isCustomerIO ? (
                        <CustomerIOImportSteps provider={selectedProvider} />
                    ) : (
                        <ProviderImportPanel provider={selectedProvider} />
                    )}
                </div>
            )}
        </LemonModal>
    )
}
