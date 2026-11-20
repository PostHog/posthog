import { useActions, useValues } from 'kea'

import { LemonDisabledArea, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { QuillChartOptionSwitch } from 'lib/components/ChartOptions/QuillChartOptionSwitch'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { InsightLogicProps } from '~/types'

import { poeFilterLogic } from './poeFilterLogic'

const POE_INFO =
    'Overrides the default person property mode for this insight to use query-time person properties instead of event-time properties. This can be useful when person data is updated after the event, but it can also slow queries significantly.'
const POE_DOCS_URL = 'https://posthog.com/docs/how-posthog-works/queries#filtering-on-person-properties'

interface PoeFilterProps {
    insightProps: InsightLogicProps
}

export function PoeFilter({ insightProps }: PoeFilterProps): JSX.Element {
    const { poeMode } = useValues(poeFilterLogic(insightProps))
    const { hasDataWarehouseSeries } = useValues(insightVizDataLogic(insightProps))
    const { setPoeMode } = useActions(poeFilterLogic(insightProps))
    const quillSurface = useQuillSurface()
    const disabledReason = hasDataWarehouseSeries
        ? 'Data warehouse insights always use the latest table properties.'
        : undefined
    const onChange = (checked: boolean): void => setPoeMode(checked ? 'person_id_override_properties_joined' : null)

    if (quillSurface) {
        return (
            <QuillChartOptionSwitch
                label="Use person properties from query time"
                info={POE_INFO}
                infoLink={POE_DOCS_URL}
                checked={!!poeMode}
                onChange={onChange}
                disabledReason={disabledReason}
            />
        )
    }

    return (
        <LemonDisabledArea className="flex items-center gap-1 w-fit" disabledReason={disabledReason}>
            <LemonLabel info={POE_INFO} infoLink={POE_DOCS_URL}>
                Use person properties from query time
            </LemonLabel>
            <LemonSwitch className="m-2" disabled={!!disabledReason} onChange={onChange} checked={!!poeMode} />
        </LemonDisabledArea>
    )
}
