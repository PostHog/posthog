import { useMemo } from 'react'

import { Button, Text } from '@posthog/quill'
import { ProportionBar } from '@posthog/quill-charts'
import type { ProportionBarConfig, Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import type { LemonTagType } from 'lib/lemon-ui/LemonTag'

import type { AEOBrandSentimentApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityTag } from './AiVisibilityTag'
import { SENTIMENT_LABELS } from './answerSentiment'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { formatShare } from './shares'

const TAG_TYPES: Record<string, LemonTagType> = { positive: 'success', neutral: 'muted', negative: 'danger' }

// The bar's own legend prints each share twice, as a share and as a value, so labelled chips stand in for it.
const LEGEND_HIDDEN: ProportionBarConfig = { legend: { show: false } }

const SHARES: { key: 'positive_share' | 'neutral_share' | 'negative_share'; label: string; type: LemonTagType }[] = [
    { key: 'positive_share', label: 'Positive', type: 'success' },
    { key: 'neutral_share', label: 'Neutral', type: 'muted' },
    { key: 'negative_share', label: 'Negative', type: 'danger' },
]

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
            <div className="flex flex-col gap-2">
                <ProportionBar
                    series={series}
                    theme={theme}
                    config={LEGEND_HIDDEN}
                    valueFormatter={formatShare}
                    dataAttr="content-autopilot-brand-sentiment-bar"
                />
                <div className="flex flex-wrap items-center gap-1" data-attr="content-autopilot-brand-sentiment-shares">
                    {SHARES.map(({ key, label, type }) => {
                        const share = sentiment[key]
                        return (
                            <AiVisibilityTag key={key} type={type}>
                                <span className="opacity-75">{label}</span>{' '}
                                <span className="tabular-nums" translate="no">
                                    {share === null ? '-' : formatShare(share)}
                                </span>
                            </AiVisibilityTag>
                        )
                    })}
                </div>
            </div>
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
