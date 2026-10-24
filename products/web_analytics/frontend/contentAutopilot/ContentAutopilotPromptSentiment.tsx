import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { PromptSentimentCounts, PromptSentimentSummary } from './promptReport'
import { engineLabel } from './utils'

const LABELS: { key: keyof PromptSentimentCounts; label: string; stroke: string }[] = [
    { key: 'positive', label: 'Positive', stroke: 'var(--success)' },
    { key: 'neutral', label: 'Neutral', stroke: 'var(--border-bold)' },
    { key: 'negative', label: 'Negative', stroke: 'var(--danger)' },
]

const engineCounts = (row: PromptSentimentCounts): string =>
    LABELS.map(({ key, label }) => `${row[key]} ${label.toLowerCase()}`).join(', ')

export const ContentAutopilotPromptSentiment = ({ summary }: { summary: PromptSentimentSummary }): JSX.Element => {
    if (summary.scored === 0) {
        return (
            <p className="m-0 text-muted">
                No sentences mention you yet, so there is nothing to score.
                {summary.unscored > 0
                    ? ` ${pluralize(summary.unscored, 'answer')} do mention you and get scored after the next run.`
                    : ''}
            </p>
        )
    }
    return (
        <div className="@container/sentiment">
            <div className="grid grid-cols-1 @2xl/sentiment:grid-cols-2 gap-4">
                <div className="flex flex-col gap-2">
                    <span className="text-xs text-muted">
                        {pluralize(summary.scored, 'scored answer')} in the last 30 days
                        {summary.unscored > 0 ? `, ${summary.unscored} not scored yet` : ''}
                    </span>
                    {LABELS.map(({ key, label, stroke }) => (
                        <div key={key} className="flex items-center gap-3">
                            <span className="w-16 shrink-0 text-sm">{label}</span>
                            <LemonProgress
                                percent={(summary[key] / summary.scored) * 100}
                                strokeColor={stroke}
                                className="flex-1"
                            />
                            <span className="w-24 shrink-0 text-right text-sm tabular-nums">
                                {summary[key]} ({percentage(summary[key] / summary.scored, 0)})
                            </span>
                        </div>
                    ))}
                </div>
                <div className="flex flex-col gap-2">
                    <span className="text-xs text-muted">Positive share by engine</span>
                    {summary.byEngine.map((row) => (
                        <div key={row.engine} className="flex flex-col gap-0.5">
                            <div className="flex items-center gap-3">
                                <span className="w-20 shrink-0 text-sm truncate">{engineLabel(row.engine)}</span>
                                <LemonProgress
                                    percent={(row.positive / row.scored) * 100}
                                    strokeColor="var(--success)"
                                    className="flex-1"
                                />
                                <span className="w-12 shrink-0 text-right text-sm tabular-nums">
                                    {percentage(row.positive / row.scored, 0)}
                                </span>
                            </div>
                            <span className="pl-23 text-xs text-muted">{engineCounts(row)}</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}
