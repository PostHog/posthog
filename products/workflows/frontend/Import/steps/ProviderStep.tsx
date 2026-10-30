import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { customerIOImportLogic } from '../customerIOImportLogic'

export function ProviderStep(): JSX.Element {
    const { importProviders, importProvidersLoading, selectedProvider } = useValues(customerIOImportLogic)
    const { selectProvider, loadImportProviders } = useActions(customerIOImportLogic)

    if (importProviders === null && importProvidersLoading) {
        return <LemonSkeleton className="h-16" />
    }
    if (importProviders === null) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadImportProviders }}>
                Couldn't load the tools you can import from.
            </LemonBanner>
        )
    }

    return (
        <div className="space-y-2">
            <p className="text-sm text-secondary m-0">Choose the messaging tool you're moving from.</p>
            <div className="grid gap-2 @min-[40rem]/main-content:grid-cols-2">
                {importProviders.map((provider) => (
                    <LemonButton
                        key={provider.key}
                        type="secondary"
                        fullWidth
                        active={provider.key === selectedProvider}
                        onClick={() => selectProvider(provider.key)}
                        data-attr={`messaging-import-provider-${provider.key}`}
                    >
                        <div className="flex flex-col items-start gap-0.5 py-1">
                            <span className="font-semibold">{provider.label}</span>
                            <span className="text-xs text-secondary font-normal">
                                {provider.steps.map((step) => step.label).join(', ')}
                            </span>
                        </div>
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}
