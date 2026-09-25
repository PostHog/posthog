import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { inboxRoutingLogic } from '../../logics/inboxRoutingLogic'
import type { InboxScope } from '../../types'

export function OwnershipScopeFilter(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { scope, availableReviewers } = useValues(inboxFiltersLogic)
    const { setScope } = useActions(inboxFiltersLogic)
    const logic = inboxRoutingLogic({ projectId: String(currentTeamId) })
    const { catalogue, catalogueLoading, error } = useValues(logic)
    const { loadCatalogue } = useActions(logic)
    return (
        <div className="flex flex-col gap-2">
            <LemonSelect<InboxScope>
                value={scope}
                onChange={setScope}
                size="small"
                loading={catalogueLoading}
                data-attr="inbox-ownership-scope"
                options={[
                    { options: [{ value: 'for-you', label: 'For you' }] },
                    {
                        title: 'Teams',
                        options:
                            catalogue?.teams.map((team) => ({
                                value: `team:${team.id}` as InboxScope,
                                label: `${team.name}${team.is_member ? ' (your team)' : ''}`,
                            })) ?? [],
                    },
                    {
                        title: 'Product domains',
                        options:
                            catalogue?.domains
                                .filter((domain) => !domain.archived || scope === `domain:${domain.id}`)
                                .map((domain) => ({
                                    value: `domain:${domain.id}` as InboxScope,
                                    label: `${domain.name}${domain.archived ? ' (archived)' : ''}`,
                                })) ?? [],
                    },
                    {
                        title: 'People',
                        options: availableReviewers.map((person) => ({
                            value: `teammate:${person.user_uuid}` as InboxScope,
                            label: person.name || person.email,
                        })),
                    },
                    {
                        options: [
                            { value: 'unclassified', label: 'Unclassified' },
                            { value: 'entire-project', label: 'Entire project' },
                        ],
                    },
                ]}
            />
            {error && (
                <LemonBanner type="error">
                    {error}
                    <LemonButton size="small" onClick={loadCatalogue}>
                        Try again
                    </LemonButton>
                </LemonBanner>
            )}
        </div>
    )
}
