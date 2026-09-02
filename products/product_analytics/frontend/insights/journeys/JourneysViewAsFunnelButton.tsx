import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'

import { PathsV2Item } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { journeysDataLogic } from './journeysDataLogic'

export function JourneysViewAsFunnelButton({
    logicProps,
    items,
    tooltip,
}: {
    logicProps: InsightLogicProps
    /** The segment's path items in displayed order; the logic sends them to the converter endpoint. */
    items: PathsV2Item[]
    tooltip: string
}): JSX.Element {
    const logic = journeysDataLogic(logicProps)
    const { segmentFunnelLoading } = useValues(logic)
    const { viewSegmentAsFunnel } = useActions(logic)

    return (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconOpenInNew />}
            loading={segmentFunnelLoading}
            tooltip={tooltip}
            onClick={() => viewSegmentAsFunnel(items)}
            data-attr="journeys-view-as-funnel"
        >
            View as funnel
        </LemonButton>
    )
}
