import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonModal, LemonSelect, LemonTag, Spinner } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { SourceCatalogItem, WarehouseBackedSource, signalSourcesLogic } from '../../signalSourcesLogic'
import { DataSourceSetup } from './DataSourceSetup'
import { SourceAgentIcon } from './SourceAgentIcon'

const TILE_CLASS =
    'flex min-h-20 items-start gap-3 rounded border border-primary bg-surface-primary p-3 text-left font-[inherit] text-default'

function tileDisabledReason(item: SourceCatalogItem): string | undefined {
    if (item.blockedReason) {
        return item.blockedReason
    }
    if (item.enabled) {
        return 'Already on. Manage it from the roster.'
    }
    if (item.loading) {
        return 'Saving'
    }
    return undefined
}

function SourceTile({
    item,
    onSelect,
}: {
    item: SourceCatalogItem
    onSelect: (source: WarehouseBackedSource) => void
}): JSX.Element {
    const disabledReason = tileDisabledReason(item)
    const tag = item.enabled
        ? { label: 'On', type: 'success' as const }
        : item.syncFailed
          ? { label: 'Sync failed', type: 'danger' as const }
          : item.connected
            ? { label: 'Synced', type: 'completion' as const }
            : null
    const content = (
        <>
            <div className="mt-0.5 shrink-0">
                <SourceAgentIcon agent={item.agent} size="medium" />
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-sm font-semibold leading-5">{item.agent.label}</span>
                    {item.agent.alpha && (
                        <LemonTag type="completion" size="small">
                            Alpha
                        </LemonTag>
                    )}
                    {tag && (
                        <LemonTag type={tag.type} size="small">
                            {tag.label}
                        </LemonTag>
                    )}
                </div>
                <span className="text-xs leading-4 text-secondary">{item.agent.watches}</span>
            </div>
            {item.loading && <Spinner className="text-base" />}
        </>
    )
    if (disabledReason) {
        return (
            <Tooltip title={disabledReason}>
                <div className={`${TILE_CLASS} cursor-not-allowed opacity-60`} aria-disabled>
                    {content}
                </div>
            </Tooltip>
        )
    }
    return (
        <button
            type="button"
            className={`${TILE_CLASS} cursor-pointer hover:border-bold`}
            onClick={() => onSelect(item.agent.source as WarehouseBackedSource)}
            aria-label={`${item.connected ? 'Turn on' : 'Connect'} ${item.agent.label}`}
            data-attr="signal-source-catalog-tile"
            data-source={item.agent.source}
        >
            {content}
        </button>
    )
}

function catalogGroupSummary(items: SourceCatalogItem[]): string {
    const on = items.filter((item) => item.enabled).length
    if (on === 0) {
        return `${items.length} available`
    }
    return `${on} of ${items.length} on`
}

export function SourceCatalogModal(): JSX.Element {
    const {
        sourceCatalogOpen,
        sourceCatalog,
        sourceSearchQuery,
        sourceCategory,
        sourceCategoryOptions,
        externalSourceCount,
        dataSourceSetupSource,
        dataSourceSetupOAuthRedirectUrl,
        externalAgents,
    } = useValues(signalSourcesLogic)
    const {
        closeSourceCatalog,
        closeDataSourceSetup,
        onDataSourceSetupComplete,
        setSourceSearchQuery,
        setSourceCategory,
        selectCatalogSource,
    } = useActions(signalSourcesLogic)
    const setupAgent = dataSourceSetupSource
        ? externalAgents.find((agent) => agent.source === dataSourceSetupSource)
        : undefined

    return (
        <LemonModal
            isOpen={sourceCatalogOpen}
            onClose={closeSourceCatalog}
            width={760}
            title={setupAgent ? `Connect ${setupAgent.label}` : 'Add a source'}
            description={
                setupAgent ? (
                    setupAgent.watches
                ) : (
                    // The header never scrolls, so the search and the category filter live in it and stay
                    // put while the grid scrolls underneath.
                    <div className="flex flex-col gap-3">
                        <p className="mb-0">
                            Connect a tool you already use. Agents read it alongside your PostHog data, so a support
                            ticket and the error behind it land in one report.
                        </p>
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonInput
                                type="search"
                                value={sourceSearchQuery}
                                onChange={setSourceSearchQuery}
                                placeholder={`Search ${externalSourceCount} sources`}
                                aria-label="Search sources"
                                data-attr="signal-sources-search"
                                className="min-w-40 flex-1"
                                fullWidth
                                autoFocus
                            />
                            <LemonSelect
                                value={sourceCategory}
                                onChange={setSourceCategory}
                                options={sourceCategoryOptions}
                                data-attr="signal-sources-category"
                            />
                        </div>
                    </div>
                )
            }
        >
            {dataSourceSetupSource ? (
                <DataSourceSetup
                    source={dataSourceSetupSource}
                    onComplete={() => onDataSourceSetupComplete()}
                    onCancel={closeDataSourceSetup}
                    cancelLabel="All sources"
                    oauthRedirectUrl={dataSourceSetupOAuthRedirectUrl}
                />
            ) : (
                <div className="flex flex-col gap-4">
                    {sourceCatalog.length === 0 && (
                        <LemonBanner type="info">
                            No sources match your search. Try another name or category.
                        </LemonBanner>
                    )}
                    {sourceCatalog.map((group) => (
                        <div key={group.category} className="flex flex-col gap-2">
                            <div className="flex items-baseline justify-between gap-2">
                                <h4 className="m-0 text-sm font-semibold">{group.category}</h4>
                                <span className="text-xs text-secondary">{catalogGroupSummary(group.items)}</span>
                            </div>
                            <div className="grid grid-cols-[repeat(auto-fill,minmax(13rem,1fr))] gap-2">
                                {group.items.map((item) => (
                                    <SourceTile
                                        key={item.agent.source}
                                        item={item}
                                        onSelect={(source) => selectCatalogSource(source, 'catalog')}
                                    />
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </LemonModal>
    )
}
