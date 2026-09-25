import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable, Spinner } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { inboxRoutingLogic } from '../../logics/inboxRoutingLogic'
import { DomainDefinitionModal } from './DomainDefinitionModal'
import { RoutingBatchModal } from './RoutingBatchModal'

export function RoutingPreferences(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const projectId = String(currentTeamId)
    const logic = inboxRoutingLogic({ projectId })
    const { catalogue, catalogueLoading, error, savedPreferenceLoading, batchLoading } = useValues(logic)
    const { loadCatalogue, previewDomain, setDomainExcluded, openBatch, editDomain } = useActions(logic)
    return (
        <div className="flex flex-col gap-3">
            <p className="m-0">
                Choose the product domains you can own. Your exclusions apply only to your suggestions. Disabling a rule
                allows future suggestions without refilling your backlog.
            </p>
            {error && (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadCatalogue }}>
                    {error}
                </LemonBanner>
            )}
            {catalogue === null ? (
                catalogueLoading && <Spinner />
            ) : (
                <>
                    {catalogue.suggestions.map((suggestion) => (
                        <LemonBanner
                            key={suggestion.domain.id}
                            type="info"
                            action={{
                                children: 'Review exclusion…',
                                onClick: () => previewDomain({ domainId: suggestion.domain.id }),
                            }}
                        >
                            <strong>{suggestion.domain.name}</strong>
                            <p className="m-0">{suggestion.explanation}</p>
                        </LemonBanner>
                    ))}
                    <LemonTable
                        dataSource={catalogue.domains}
                        rowKey="id"
                        emptyState="No product domains yet. Add domain definitions to start routing reports by current ownership."
                        columns={[
                            {
                                title: 'Product domains and your routing',
                                render: (_, domain) => {
                                    const excluded = catalogue.preferences.some(
                                        (preference) => preference.domain.id === domain.id && preference.excluded
                                    )
                                    return (
                                        <div className="flex flex-wrap items-center justify-between gap-3">
                                            <div className="min-w-0">
                                                <LemonButton size="small" onClick={() => editDomain(domain)}>
                                                    {domain.name}
                                                </LemonButton>
                                                <div className="text-secondary text-xs">
                                                    {domain.owning_role_name || 'No team'}
                                                </div>
                                                <div className="text-xs">
                                                    {excluded ? 'Excluded' : 'Eligible for suggestions'}
                                                </div>
                                            </div>
                                            {excluded ? (
                                                <LemonButton
                                                    size="small"
                                                    type="secondary"
                                                    loading={savedPreferenceLoading}
                                                    onClick={() =>
                                                        setDomainExcluded({ domainId: domain.id, excluded: false })
                                                    }
                                                    data-attr="inbox-routing-disable-rule"
                                                >
                                                    Allow suggestions
                                                </LemonButton>
                                            ) : (
                                                <LemonButton
                                                    size="small"
                                                    type="secondary"
                                                    loading={batchLoading}
                                                    onClick={() => previewDomain({ domainId: domain.id })}
                                                    disabledReason={
                                                        domain.archived ? 'This domain is archived' : undefined
                                                    }
                                                    data-attr="inbox-routing-preview-rule"
                                                >
                                                    Exclude domain…
                                                </LemonButton>
                                            )}
                                        </div>
                                    )
                                },
                            },
                        ]}
                    />
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() => editDomain(null)}
                        data-attr="inbox-domain-add"
                    >
                        Add product domain
                    </LemonButton>
                    {catalogue.batches.length > 0 && (
                        <>
                            <h4 className="m-0">Recent changes</h4>
                            <div className="flex flex-wrap gap-2">
                                {catalogue.batches
                                    .filter((batch) => batch.status !== 'preview')
                                    .map((batch) => (
                                        <LemonButton
                                            key={batch.id}
                                            size="small"
                                            type="secondary"
                                            onClick={() => openBatch(batch.id)}
                                            data-attr="inbox-routing-open-operation"
                                        >{`${catalogue.domains.find((domain) => domain.id === batch.domain_id)?.name ?? 'Domain'}: ${batch.status}`}</LemonButton>
                                    ))}
                            </div>
                        </>
                    )}
                </>
            )}
            <RoutingBatchModal projectId={projectId} />
            <DomainDefinitionModal projectId={projectId} />
        </div>
    )
}
