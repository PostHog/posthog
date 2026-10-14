import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { StepCatalogEntry } from './stepCatalog'
import { StepPickerBreadcrumb } from './StepPickerBreadcrumb'
import { stepPickerLogic } from './stepPickerLogic'
import { StepPickerView, providerLabelOf } from './stepPickerPresentation'
import { StepPickerProviderRow } from './StepPickerProviderRow'
import { StepPickerStepRow } from './StepPickerStepRow'

const withProvider = (entry: StepCatalogEntry): string => providerLabelOf(entry)
const withDescription = (entry: StepCatalogEntry): string => entry.description

const EMPTY_VIEW_MESSAGES: Partial<Record<StepPickerView, string>> = {
    favorites: 'No favorites yet. Star a step to keep it here.',
    recents: 'Steps you add show up here.',
}

const VIEWS_ACROSS_PROVIDERS: StepPickerView[] = ['highlights', 'favorites', 'recents']

export function StepPickerList(): JSX.Element {
    const {
        view,
        viewSteps,
        providers,
        openedProvider,
        isSearching,
        search,
        searchResults,
        isLoadingIntegrations,
        integrationsFailed,
    } = useValues(stepPickerLogic)
    const { clearSearch, loadHogFunctionTemplates } = useActions(stepPickerLogic)

    const stepList = (entries: StepCatalogEntry[], subtitle: (entry: StepCatalogEntry) => string): JSX.Element => (
        <ul className="flex flex-col gap-0.5">
            {entries.map((entry) => (
                <StepPickerStepRow key={entry.id} entry={entry} subtitle={subtitle(entry)} />
            ))}
        </ul>
    )
    const integrationsSkeleton = isLoadingIntegrations ? <LemonSkeleton className="my-1 h-10" repeat={4} /> : null
    const integrationsError = integrationsFailed ? (
        <LemonBanner type="error" action={{ children: 'Retry', onClick: loadHogFunctionTemplates }} className="mb-2">
            Couldn't load integrations. Built-in steps are still listed.
        </LemonBanner>
    ) : null

    const content = (): JSX.Element => {
        if (isSearching) {
            if (searchResults.length > 0) {
                return (
                    <>
                        {stepList(searchResults, withProvider)}
                        {integrationsSkeleton}
                    </>
                )
            }
            if (isLoadingIntegrations) {
                return <>{integrationsSkeleton}</>
            }
            return (
                <div className="flex flex-col items-center gap-2 py-12 text-center text-sm text-secondary">
                    <span>{`No steps match "${search.trim()}".`}</span>
                    <LemonButton type="secondary" size="small" onClick={clearSearch}>
                        Clear search
                    </LemonButton>
                </div>
            )
        }
        if (openedProvider) {
            return stepList(openedProvider.entries, withDescription)
        }
        if (view === 'all' || view === 'posthog') {
            return (
                <div className="flex flex-col gap-4">
                    <section>
                        <h4 className="mb-1 mt-0 px-1 text-xs font-semibold uppercase tracking-wide text-secondary">
                            PostHog
                        </h4>
                        <ul className="flex flex-col gap-0.5">
                            {providers.posthog.map((provider) => (
                                <StepPickerProviderRow key={provider.id} provider={provider} />
                            ))}
                        </ul>
                    </section>
                    {view === 'all' ? (
                        <section>
                            <h4 className="mb-1 mt-0 px-1 text-xs font-semibold uppercase tracking-wide text-secondary">
                                Third party, A to Z
                            </h4>
                            <ul className="flex flex-col gap-0.5">
                                {providers.thirdParty.map((provider) =>
                                    provider.entries.length === 1 ? (
                                        <StepPickerStepRow
                                            key={provider.id}
                                            entry={provider.entries[0]}
                                            subtitle={provider.entries[0].description}
                                        />
                                    ) : (
                                        <StepPickerProviderRow key={provider.id} provider={provider} />
                                    )
                                )}
                            </ul>
                            {integrationsSkeleton}
                        </section>
                    ) : null}
                </div>
            )
        }
        if (!VIEWS_ACROSS_PROVIDERS.includes(view)) {
            return stepList(viewSteps, withDescription)
        }
        const emptyViewMessage = EMPTY_VIEW_MESSAGES[view]
        if (viewSteps.length === 0 && emptyViewMessage && !isLoadingIntegrations && !integrationsFailed) {
            return <div className="py-12 text-center text-sm text-secondary">{emptyViewMessage}</div>
        }
        return (
            <>
                {stepList(viewSteps, withProvider)}
                {integrationsSkeleton}
            </>
        )
    }

    return (
        <section
            aria-label="Steps"
            className="flex w-[28rem] shrink-0 flex-col border-r @max-[64rem]/step-picker:w-[22rem] @max-[44rem]/step-picker:w-auto @max-[44rem]/step-picker:min-w-0 @max-[44rem]/step-picker:flex-1 @max-[44rem]/step-picker:border-r-0"
        >
            <StepPickerBreadcrumb />
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
                {integrationsError}
                {content()}
            </div>
        </section>
    )
}
