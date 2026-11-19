import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { DataVisualizationNode } from '~/queries/schema/schema-general'

import { ContentAutopilotPromptQueryTile } from './ContentAutopilotPromptQueryTile'
import type { PromptSentimentCounts, PromptSentimentSummary } from './promptReport'

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
            <p className="m-0 text-muted">
                {summary.unscored > 0
                    ? `${pluralize(summary.unscored, 'answer')} mention you but have not been scored yet.`
                    : 'No sentences mention you yet, so there is nothing to score.'}
            </p>
        )
    }
    return (
        <div className="flex flex-col gap-3">
            <p className="m-0 text-sm">
                {pluralize(summary.scored, 'scored answer')} in the last 30 days:{' '}
                {LABELS.map(({ key, label }, index) => (
                    <span key={key}>
                        {index > 0 ? ', ' : ''}
                        <span className="font-semibold tabular-nums">{summary[key]}</span> {label} (
                        {percentage(summary[key] / summary.scored, 0)})
                    </span>
                ))}
                {summary.unscored > 0 ? `. ${pluralize(summary.unscored, 'answer')} not scored yet.` : '.'}
            </p>
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
