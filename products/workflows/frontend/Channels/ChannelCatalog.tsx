import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { ChannelCatalogCard } from './ChannelCatalogCard'
import { channelCatalogLogic } from './channelCatalogLogic'
import { CATALOG_CHANNELS, CATALOG_GRID_CLASS } from './channelSummary'

/** Every channel a workflow can send through, with whether this project has it set up. */
export function ChannelCatalog(): JSX.Element {
    const { channels, activeCount, integrationsLoadFailed, integrationsLoading, integrationsLoadError } =
        useValues(channelCatalogLogic)
    const { loadIntegrations } = useActions(channelCatalogLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <section className="flex flex-col gap-2" data-attr="workflows-channel-catalog">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="mb-0 text-base font-semibold">Available channels</h3>
                {channels && (
                    <span className="text-secondary text-sm">{`${activeCount} of ${channels.length} active`}</span>
                )}
            </div>
            {channels ? (
                <>
                    {integrationsLoadFailed && (
                        <div className="flex flex-wrap items-center gap-2 text-xs text-secondary">
                            <span>Couldn't refresh your channels. Showing the last loaded connections.</span>
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={loadIntegrations}
                                loading={integrationsLoading}
                            >
                                Try again
                            </LemonButton>
                        </div>
                    )}
                    <div className={CATALOG_GRID_CLASS}>
                        {channels.map((channel) => (
                            <ChannelCatalogCard
                                key={channel.kind}
                                channel={channel}
                                disabledReason={restrictedReason}
                            />
                        ))}
                    </div>
                </>
            ) : integrationsLoadFailed ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadIntegrations, loading: integrationsLoading }}
                >
                    {integrationsLoadError || "Couldn't load your channels."}
                </LemonBanner>
            ) : (
                <div className={CATALOG_GRID_CLASS}>
                    {CATALOG_CHANNELS.map((kind) => (
                        <LemonSkeleton key={kind} className="h-20" />
                    ))}
                </div>
            )}
        </section>
    )
}
