import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonBanner, LemonButton, LemonInput, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { signalSourcesLogic } from '../../signalSourcesLogic'
import { SourceCatalogTile } from './SourceCatalogTile'

export function SourceCatalog(): JSX.Element {
    const {
        sourceCatalog,
        sourceSearchQuery,
        sourceCategory,
        sourceCategoryOptions,
        visibleSourceRecommendations,
        sourceConfigs,
        sourceConfigsLoadFailed,
        dataWarehouseSources,
        sourcesLoadError,
        integrationsLoading,
        onboardingStateLoading,
    } = useValues(signalSourcesLogic)
    const { setSourceSearchQuery, setSourceCategory, hideSourceRecommendations, sourceCatalogViewed } =
        useActions(signalSourcesLogic)
    const loading =
        (sourceConfigs === null && !sourceConfigsLoadFailed) || (dataWarehouseSources === null && !sourcesLoadError)
    const unavailable =
        (sourceConfigs === null && sourceConfigsLoadFailed) || (dataWarehouseSources === null && sourcesLoadError)
    const viewed = useRef(false)

    useEffect(() => {
        if (!loading && !unavailable && !integrationsLoading && !onboardingStateLoading && !viewed.current) {
            viewed.current = true
            sourceCatalogViewed()
        }
    }, [loading, unavailable, integrationsLoading, onboardingStateLoading, sourceCatalogViewed])

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    value={sourceSearchQuery}
                    onChange={setSourceSearchQuery}
                    placeholder="Search available sources"
                    aria-label="Search sources"
                    data-attr="signal-sources-search"
                    className="min-w-40 flex-1"
                    fullWidth
                />
                <LemonSelect
                    value={sourceCategory}
                    onChange={setSourceCategory}
                    options={sourceCategoryOptions}
                    data-attr="signal-sources-category"
                />
            </div>
            {unavailable ? (
                <LemonBanner type="warning">
                    Couldn't load available sources. Retry loading your connections above.
                </LemonBanner>
            ) : loading ? (
                <LemonSkeleton className="h-40" />
            ) : sourceCatalog.length === 0 ? (
                <LemonBanner type="info">
                    {sourceSearchQuery || sourceCategory
                        ? 'No available sources match your search. Try another name or category.'
                        : 'All available sources are connected. Manage them in Your sources above.'}
                </LemonBanner>
            ) : (
                sourceCatalog.map((group) => (
                    <div
                        key={group.category}
                        className="flex flex-col gap-2 pt-2"
                        data-attr={
                            group.category === 'Recommended for you' ? 'signal-source-recommendations' : undefined
                        }
                    >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <h4 className="m-0 text-sm font-semibold">{group.category}</h4>
                            {group.category === 'Recommended for you' && visibleSourceRecommendations.length > 0 && (
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    onClick={hideSourceRecommendations}
                                    data-attr="signal-source-recommendations-hide"
                                >
                                    Hide recommendations
                                </LemonButton>
                            )}
                        </div>
                        <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,13rem),1fr))] gap-2">
                            {group.items.map((item) => (
                                <SourceCatalogTile key={item.agent.source} item={item} />
                            ))}
                        </div>
                    </div>
                ))
            )}
        </div>
    )
}
