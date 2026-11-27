import { useMemo } from 'react'

import { Button, Text } from '@posthog/quill'
import { ProportionBar } from '@posthog/quill-charts'
import type { Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import type { LemonTagType } from 'lib/lemon-ui/LemonTag'

import type { AEOBrandSentimentApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityTag } from './AiVisibilityTag'
import { SENTIMENT_LABELS } from './answerSentiment'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { formatShare } from './shares'

const TAG_TYPES: Record<string, LemonTagType> = { positive: 'success', neutral: 'muted', negative: 'danger' }

/** How the scored answers naming a brand speak about it, with a few of their sentences. */
export const ContentAutopilotBrandSentiment = ({
    sentiment,
    onOpenPrompt,
}: {
    sentiment: AEOBrandSentimentApi
    onOpenPrompt: (promptId: string) => void
}): JSX.Element => {
    const theme = useChartTheme()
    // Read on every render so the colors follow the color mode.
    const positive = getColorVar('success')
    const neutral = getColorVar('color-text-tertiary')
    const negative = getColorVar('danger')
    const series = useMemo<Series[]>(
        () => [
            { key: 'positive', label: 'Positive', color: positive, data: [sentiment.positive_share ?? 0] },
            { key: 'neutral', label: 'Neutral', color: neutral, data: [sentiment.neutral_share ?? 0] },
            { key: 'negative', label: 'Negative', color: negative, data: [sentiment.negative_share ?? 0] },
        ],
        [sentiment, positive, neutral, negative]
    )

    if (sentiment.scored === 0) {
        return (
            <Text
                size="xs"
                variant="muted"
                render={<p className="m-0" />}
                data-attr="content-autopilot-brand-sentiment-empty"
            >
                No answer in this date range has a scored sentence about this brand yet.
            </Text>
        )
    }
    return (
        <div className="flex flex-col gap-4" data-attr="content-autopilot-brand-sentiment">
            <ProportionBar
                series={series}
                theme={theme}
                valueFormatter={formatShare}
                dataAttr="content-autopilot-brand-sentiment-bar"
            />
            {sentiment.examples.length > 0 ? (
                <ul className="m-0 flex flex-col gap-2 p-0" data-attr="content-autopilot-brand-sentiment-examples">
                    {sentiment.examples.map((example, index) => (
                        <li
                            key={`${example.prompt_id}-${index}`}
                            className="flex list-none flex-col gap-1 rounded-md border border-border p-3"
                        >
                            <span className="flex flex-wrap items-center gap-2">
                                <AiVisibilityTag type={TAG_TYPES[example.sentiment] ?? 'default'}>
                                    {SENTIMENT_LABELS[example.sentiment] ?? example.sentiment}
                                </AiVisibilityTag>
                                <ContentAutopilotEngineLabel engine={example.engine} />
                                <Button
                                    variant="link-muted"
                                    size="inline"
                                    className="ml-auto"
                                    onClick={() => onOpenPrompt(example.prompt_id)}
                                    data-attr="content-autopilot-brand-sentiment-prompt"
                                >
                                    Open prompt
                                </Button>
                            </span>
                            <Text size="sm" render={<blockquote className="m-0" />}>
                                {example.sentence}
                            </Text>
                        </li>
                    ))}
                </ul>
            ) : null}
        </div>
    )
}
