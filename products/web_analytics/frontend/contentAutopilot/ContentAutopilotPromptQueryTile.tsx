import clsx from 'clsx'
import { ReactNode } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import { Query } from '~/queries/Query/Query'
import { DataTableNode, DataVisualizationNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

/** One report tile: a card with the web analytics tile header, a read-only query inside, and a way to open
 *  the same query as an insight so it can be saved or added to a dashboard. */
export const ContentAutopilotPromptQueryTile = ({
    title,
    query,
    uniqueKey,
    context,
    actions,
    footer,
    className,
    bodyClassName,
    'data-attr': dataAttr,
}: {
    title: string
    query: DataTableNode | DataVisualizationNode
    uniqueKey: string
    context?: QueryContext
    actions?: ReactNode
    footer?: ReactNode
    className?: string
    bodyClassName?: string
    'data-attr': string
}): JSX.Element => (
    <PagePerformanceCard className={clsx('min-w-0', className)} footer={footer}>
        <PagePerformanceCardHeader
            title={title}
            actions={
                <div className="flex flex-wrap items-center gap-2">
                    {actions}
                    <LemonButton
                        size="small"
                        icon={<IconOpenInNew />}
                        to={urls.insightNew({ query })}
                        targetBlank
                        tooltip="Open as insight"
                        aria-label="Open as insight"
                        data-attr={`${dataAttr}-open-insight`}
                    />
                </div>
            }
        />
        {/* No flex-1 here: in the card's column layout it would override a fixed chart height from `bodyClassName`. */}
        <div className={clsx('flex flex-col min-h-0 min-w-0', bodyClassName)} data-attr={dataAttr}>
            <Query uniqueKey={uniqueKey} query={query} readOnly embedded context={context} />
        </div>
    </PagePerformanceCard>
)
