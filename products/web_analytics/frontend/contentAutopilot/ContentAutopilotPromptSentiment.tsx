import { Text } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import type { DataVisualizationNode } from '~/queries/schema/schema-general'

import { ContentAutopilotPromptQueryTile } from './ContentAutopilotPromptQueryTile'
import type { PromptSentimentCounts, PromptSentimentSummary } from './promptReport'
import { formatShare } from './shares'

const LABELS: { key: keyof PromptSentimentCounts; label: string }[] = [
    { key: 'positive', label: 'positive' },
    { key: 'neutral', label: 'neutral' },
    { key: 'negative', label: 'negative' },
]

export const ContentAutopilotPromptSentiment = ({
    summary,
    query,
}: {
    summary: PromptSentimentSummary
    query: DataVisualizationNode
}): JSX.Element => {
    if (summary.scored === 0) {
        return (
            <Text size="xs" variant="muted" className="m-0">
                {summary.unscored > 0
                    ? `${pluralize(summary.unscored, 'answer')} mention you but have not been scored yet.`
                    : 'No sentences mention you yet, so there is nothing to score.'}
            </Text>
        )
    }
    return (
        <div className="flex flex-col gap-3">
            <Text size="xs" className="m-0">
                {pluralize(summary.scored, 'scored answer')} in the last 30 days:{' '}
                {LABELS.map(({ key, label }, index) => (
                    <span key={key}>
                        {index > 0 ? ', ' : ''}
                        <span className="font-semibold tabular-nums">{summary[key]}</span> {label} (
                        {formatShare(summary[key] / summary.scored)})
                    </span>
                ))}
                {summary.unscored > 0 ? `. ${pluralize(summary.unscored, 'answer')} not scored yet.` : '.'}
            </Text>
            <ContentAutopilotPromptQueryTile
                title="Scored answers per engine"
                query={query}
                uniqueKey={`aeo-prompt-sentiment-${query.source.values?.prompt_id ?? ''}`}
                bodyClassName="h-64 p-2"
                data-attr="content-autopilot-prompt-sentiment-tile"
            />
        </div>
    )
}
