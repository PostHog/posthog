import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'
import { Button, Item, ItemContent, Text } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { InsightLogicProps } from '~/types'

interface SamplingDeprecationNoticeProps {
    insightProps: InsightLogicProps
}

export function SamplingDeprecationNotice({ insightProps }: SamplingDeprecationNoticeProps): JSX.Element | null {
    const { samplingFactor } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const quillSurface = useQuillSurface()

    const hasSampling = samplingFactor != null && samplingFactor < 1

    if (!hasSampling) {
        return null
    }

    const disableSampling = (): void => {
        updateQuerySource({ samplingFactor: null })
    }

    if (quillSurface) {
        return (
            <Item variant="outline" tone="warning" size="sm">
                <ItemContent>
                    <Text size="xs" className="m-0">
                        This insight currently uses {(samplingFactor * 100).toFixed(0)}% sampling. Sampling is being
                        deprecated and will be removed in a future release.{' '}
                        <Button variant="link" size="inline" onClick={disableSampling}>
                            Disable it now
                        </Button>{' '}
                        and run on full data.
                    </Text>
                </ItemContent>
            </Item>
        )
    }

    return (
        <LemonBanner type="warning">
            <span>
                This insight currently uses {(samplingFactor * 100).toFixed(0)}% sampling. Sampling is being deprecated
                and will be removed in a future release.{' '}
                <button className="text-link font-semibold" onClick={disableSampling}>
                    Disable it now
                </button>{' '}
                and run on full data.
            </span>
        </LemonBanner>
    )
}
