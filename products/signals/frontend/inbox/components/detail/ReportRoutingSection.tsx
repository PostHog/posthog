import { useActions, useValues } from 'kea'

import { IconPeople } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { inboxRoutingLogic } from '../../logics/inboxRoutingLogic'
import { reportRoutingLogic } from '../../logics/reportRoutingLogic'
import { RoutingBatchModal } from '../routing/RoutingBatchModal'
import { DetailSection } from './DetailSection'

export function ReportRoutingSection({ reportId }: { reportId: string }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const projectId = String(currentTeamId)
    const routing = reportRoutingLogic({ projectId, reportId })
    const { state, stateLoading, domainId, teamId, error } = useValues(routing)
    const { loadState, notMe, restore, setDomainId, setTeamId, saveRouting } = useActions(routing)
    const { catalogue, catalogueLoading, error: catalogueError } = useValues(inboxRoutingLogic({ projectId }))
    const { previewDomain, loadCatalogue } = useActions(inboxRoutingLogic({ projectId }))
    const domain = state?.routing?.domain
    const excludedDomain =
        !!state?.routing?.accepted &&
        catalogue?.preferences.some((preference) => preference.excluded && preference.domain.id === domain?.id)

    return (
        <DetailSection title="Routing" icon={<IconPeople />}>
            <div className="flex flex-col gap-3">
                {error && (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadState }}>
                        {error}
                    </LemonBanner>
                )}
                {catalogueError && (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadCatalogue }}>
                        {catalogueError}
                    </LemonBanner>
                )}
                {state === null ? (
                    stateLoading ? (
                        <Spinner />
                    ) : null
                ) : (
                    <>
                        <p className="m-0 text-xs text-secondary">
                            {state.routing?.explanation ||
                                'Suggested owners are people who can take on this work. Review the domain and team if this reached the wrong person.'}
                        </p>
                        {state.routing && !state.routing.accepted && (
                            <LemonBanner type="info">
                                The domain is uncertain. This report remains available for shared triage.
                            </LemonBanner>
                        )}
                        <label className="flex flex-col gap-1 text-xs">
                            <span>Product domain</span>
                            <LemonSelect
                                value={domainId}
                                onChange={setDomainId}
                                loading={catalogueLoading}
                                disabledReason={
                                    stateLoading
                                        ? 'Saving routing'
                                        : !catalogue
                                          ? 'Load routing options first'
                                          : undefined
                                }
                                options={[
                                    { value: null, label: 'Unclassified' },
                                    ...(catalogue?.domains
                                        .filter((item) => !item.archived)
                                        .map((item) => ({ value: item.id, label: item.name })) ?? []),
                                ]}
                                data-attr="inbox-routing-domain"
                            />
                        </label>
                        <label className="flex flex-col gap-1 text-xs">
                            <span>Responsible team</span>
                            <LemonSelect
                                value={teamId}
                                onChange={setTeamId}
                                loading={catalogueLoading}
                                disabledReason={
                                    stateLoading
                                        ? 'Saving routing'
                                        : !catalogue
                                          ? 'Load routing options first'
                                          : undefined
                                }
                                options={[
                                    { value: null, label: 'No team' },
                                    ...(catalogue?.teams.map((item) => ({ value: item.id, label: item.name })) ?? []),
                                ]}
                                data-attr="inbox-routing-team"
                            />
                        </label>
                        <div className="flex flex-wrap gap-2">
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={saveRouting}
                                loading={stateLoading}
                                disabledReason={!catalogue ? 'Load routing options first' : undefined}
                                data-attr="inbox-routing-save"
                            >
                                Save routing
                            </LemonButton>
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={state.personal.excluded ? restore : notMe}
                                loading={stateLoading}
                                disabledReason={
                                    state.personal.excluded && excludedDomain
                                        ? 'A domain rule still applies. Update it in your routing settings.'
                                        : undefined
                                }
                                data-attr="inbox-routing-not-me"
                            >
                                {state.personal.excluded
                                    ? 'Undo Not me'
                                    : state.personal.has_active_claim
                                      ? 'Remove my suggestion'
                                      : 'Not me'}
                            </LemonButton>
                        </div>
                        {state.personal.excluded && (
                            <p className="m-0 text-xs">You will not be suggested again for this report.</p>
                        )}
                        {state.personal.has_active_claim && (
                            <LemonBanner type="info">
                                You still own work on this report. Removing a suggestion keeps that work assigned to
                                you. Hand it off or release your claim separately.
                            </LemonBanner>
                        )}
                        {domain && state.routing?.accepted && (
                            <LemonButton
                                size="small"
                                onClick={() => previewDomain({ domainId: domain.id })}
                                data-attr="inbox-routing-preview-domain"
                            >
                                {`Stop suggesting ${domain.name} to me`}
                            </LemonButton>
                        )}
                    </>
                )}
            </div>
            <RoutingBatchModal projectId={projectId} />
        </DetailSection>
    )
}
