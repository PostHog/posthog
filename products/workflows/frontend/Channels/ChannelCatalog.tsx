import { useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { CATALOG_CHANNELS } from './channelCatalog'
import { ChannelCatalogCard } from './ChannelCatalogCard'
import { channelCatalogLogic } from './channelCatalogLogic'

const GRID_CLASS = 'grid gap-2 grid-cols-1 @min-[44rem]/main-content:grid-cols-2 @min-[72rem]/main-content:grid-cols-3'

/** Every channel a workflow can send through, with whether this project has it set up. */
export function ChannelCatalog(): JSX.Element {
    const { channels, activeCount, integrationsLoadFailed } = useValues(channelCatalogLogic)
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
                <div className={GRID_CLASS}>
                    {channels.map((channel) => (
                        <ChannelCatalogCard key={channel.kind} channel={channel} disabledReason={restrictedReason} />
                    ))}
                </div>
            ) : integrationsLoadFailed ? (
                <LemonBanner type="error">Couldn't load your channels. Refresh the page to try again.</LemonBanner>
            ) : (
                <div className={GRID_CLASS}>
                    {CATALOG_CHANNELS.map((kind) => (
                        <LemonSkeleton key={kind} className="h-20" />
                    ))}
                </div>
            )}
        </section>
    )
}
