import clsx from 'clsx'
import { useActions } from 'kea'

import { IconGraph } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { InsightLogicProps } from '~/types'

import { audienceEngagementLogic } from './audienceEngagementLogic'
import { AudienceEngagementTile } from './audienceEngagementTiles'

export function AudienceEngagementTileCard({ tile }: { tile: AudienceEngagementTile }): JSX.Element {
    const { insightOpened } = useActions(audienceEngagementLogic)
    const insightProps: InsightLogicProps = {
        dashboardItemId: `new-AdHoc.audience-engagement-${tile.key}`,
        dataNodeCollectionId: `audience-engagement-${tile.key}`,
        query: tile.query,
    }

    return (
        <LemonCard
            hoverEffect={false}
            className={clsx(
                'flex flex-col gap-2 p-0 min-w-0',
                tile.fullWidth && '@min-[64rem]/main-content:col-span-2'
            )}
            data-attr={`audience-engagement-tile-${tile.key}`}
        >
            <div className="flex flex-wrap items-start justify-between gap-2 px-4 pt-3">
                <div className="min-w-0">
                    <h3 className="font-semibold m-0">{tile.name}</h3>
                    <p className="text-secondary text-xs m-0">{tile.description}</p>
                </div>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconGraph />}
                    to={urls.insightNew({ query: tile.query })}
                    onClick={() => insightOpened(tile.key)}
                    aria-label={`Open ${tile.name} as insight`}
                    data-attr="audience-engagement-open-insight"
                >
                    Open as insight
                </LemonButton>
            </div>
            <div className="min-h-0 flex-1 px-2 pb-2">
                <Query
                    query={tile.query}
                    readOnly
                    inSharedMode
                    context={{
                        insightProps,
                        suppressSlowQuerySuggestions: true,
                        emptyStateHeading: tile.emptyStateHeading,
                        emptyStateDetail: 'Engagement events are recorded from the moment they are turned on.',
                    }}
                />
            </div>
        </LemonCard>
    )
}
