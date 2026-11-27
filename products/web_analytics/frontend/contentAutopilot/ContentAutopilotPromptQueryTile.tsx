import clsx from 'clsx'
import { ReactNode } from 'react'

import { Query } from '~/queries/Query/Query'
import { DataTableNode, DataVisualizationNode, InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { AiVisibilityCard } from './AiVisibilityCard'
import { ContentAutopilotOpenInsightButton } from './ContentAutopilotOpenInsightButton'

/** One report tile: a card with a title row, a read-only query inside, and a way to open
 *  the same query as an insight so it can be saved or added to a dashboard. */
export const ContentAutopilotPromptQueryTile = ({
    title,
    description,
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
    description?: string
    query: DataTableNode | DataVisualizationNode | InsightVizNode
    uniqueKey: string
    context?: QueryContext
    actions?: ReactNode
    footer?: ReactNode
    className?: string
    bodyClassName?: string
    'data-attr': string
}): JSX.Element => (
    <AiVisibilityCard
        title={title}
        description={description}
        className={className}
        footer={footer}
        actions={
            <>
                {actions}
                <ContentAutopilotOpenInsightButton query={query} data-attr={`${dataAttr}-open-insight`} />
            </>
        }
    >
        {/* No flex-1 here: in the card's column layout it would override a fixed chart height from `bodyClassName`. */}
        <div className={clsx('flex flex-col min-h-0 min-w-0', bodyClassName)} data-attr={dataAttr}>
            <Query uniqueKey={uniqueKey} query={query} readOnly embedded context={context} />
        </div>
    </AiVisibilityCard>
)
