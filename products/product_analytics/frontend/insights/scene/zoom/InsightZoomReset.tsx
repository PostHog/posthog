import { useActions, useValues } from 'kea'

import { IconUndo } from '@posthog/icons'
import { Button } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { insightZoomLogic } from './insightZoomLogic'

export function InsightZoomReset({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { canResetZoom } = useValues(insightZoomLogic(insightProps))
    const { resetZoom } = useActions(insightZoomLogic(insightProps))

    if (!canResetZoom) {
        return null
    }

    return (
        <Button variant="outline" size="sm" onClick={() => resetZoom()} data-attr="quill-insight-reset-zoom">
            <IconUndo />
            Reset zoom
        </Button>
    )
}
