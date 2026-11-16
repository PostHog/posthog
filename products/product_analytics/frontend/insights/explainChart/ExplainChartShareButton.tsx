import { useActions, useValues } from 'kea'

import { IconShare } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import type { InsightLogicProps } from '~/types'

import { explainChartLogic } from './explainChartLogic'

export function ExplainChartShareButton({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    const { storyLinkCopying, shareDisabledReason } = useValues(explainChartLogic(insightProps))
    const { copyStoryLink } = useActions(explainChartLogic(insightProps))
    const quillSurface = useQuillSurface()

    return quillSurface ? (
        <span data-quill>
            <Button
                variant="outline"
                size="sm"
                disabledReason={shareDisabledReason}
                loading={storyLinkCopying}
                onClick={copyStoryLink}
                data-attr="explain-chart-share"
            >
                <IconShare />
                Share
            </Button>
        </span>
    ) : (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconShare />}
            disabledReason={shareDisabledReason}
            loading={storyLinkCopying}
            onClick={copyStoryLink}
            data-attr="explain-chart-share"
        >
            Share
        </LemonButton>
    )
}
