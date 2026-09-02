import { IconExternal } from '@posthog/icons'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, TrendsQuery } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { insightNewUrl } from './queries'

export function ChartCard({
    title,
    description,
    query,
    chartKey,
}: {
    title: string
    description: string
    query: InsightVizNode<TrendsQuery>
    chartKey: string
}): JSX.Element {
    const insightProps: InsightLogicProps = {
        dashboardItemId: `new-AdHoc.error-tracking-insights-${chartKey}`,
        dataNodeCollectionId: `error-tracking-insights-${chartKey}`,
        query,
    }

    return (
        <div className="h-100 flex flex-col rounded-md border bg-surface-primary">
            <div className="flex shrink-0 items-center justify-between p-4 pb-2">
                <div>
                    <h3 className="font-semibold text-sm m-0">{title}</h3>
                    <p className="text-xs text-secondary m-0">{description}</p>
                </div>
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                variant="default"
                                size="icon-sm"
                                nativeButton={false}
                                render={<LinkPrimitive to={insightNewUrl(query)} target="_blank" />}
                                aria-label="Open as insight"
                            />
                        }
                    >
                        <IconExternal />
                    </TooltipTrigger>
                    <TooltipContent>Open as insight</TooltipContent>
                </Tooltip>
            </div>
            <div className="ErrorTracking__insights min-h-0 flex-1 px-4 pt-2 pb-4">
                <Query
                    query={query}
                    readOnly={true}
                    context={{ insightProps, suppressSlowQuerySuggestions: true }}
                    inSharedMode={true}
                />
            </div>
        </div>
    )
}
