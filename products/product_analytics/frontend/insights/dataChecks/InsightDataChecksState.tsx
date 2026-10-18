import { useMountedLogic } from 'kea'

import type { InsightLogicProps } from '~/types'

import { insightDataChecksLogic } from './insightDataChecksLogic'

/** Holds the result of the data checks while the chart is on the page. The mark itself comes and goes. */
export function InsightDataChecksState({ insightProps }: { insightProps: InsightLogicProps }): null {
    useMountedLogic(insightDataChecksLogic(insightProps))
    return null
}
