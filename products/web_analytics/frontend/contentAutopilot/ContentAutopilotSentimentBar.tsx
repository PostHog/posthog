import { useMemo } from 'react'

import { ProportionBar } from '@posthog/quill-charts'
import type { Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { pluralize } from 'lib/utils/strings'

import type { PromptSentimentSummary } from './promptReport'

/** Positive, neutral and negative answers as one bar, so the tone of the answers reads at a glance. */
export const ContentAutopilotSentimentBar = ({ summary }: { summary: PromptSentimentSummary }): JSX.Element => {
    const theme = useChartTheme()
    // Read on every render so the colors follow the color mode.
    const positive = getColorVar('success')
    const neutral = getColorVar('color-text-tertiary')
    const negative = getColorVar('danger')
    const series = useMemo<Series[]>(
        () => [
            { key: 'positive', label: 'Positive', color: positive, data: [summary.positive] },
            { key: 'neutral', label: 'Neutral', color: neutral, data: [summary.neutral] },
            { key: 'negative', label: 'Negative', color: negative, data: [summary.negative] },
        ],
        [summary, positive, neutral, negative]
    )
    if (summary.scored === 0) {
        return (
            <p className="m-0 text-muted">
                {summary.unscored > 0
                    ? `${pluralize(summary.unscored, 'answer')} mention you but have not been scored yet.`
                    : 'No sentences mention you yet, so there is nothing to score.'}
            </p>
        )
    }
    return (
        <ProportionBar
            series={series}
            theme={theme}
            valueFormatter={(value) => pluralize(value, 'answer')}
            dataAttr="content-autopilot-prompt-sentiment-bar"
        />
    )
}
