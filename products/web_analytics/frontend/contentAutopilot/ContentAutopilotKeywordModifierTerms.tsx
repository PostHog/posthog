import { LemonTable, LemonTag } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'

import type { AEOKeywordModifierApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { isCitationGap } from './keywordsReport'
import { engineLabel } from './utils'

/** The words of one modifier group, with gaps against the baseline cited rate highlighted. */
export const ContentAutopilotKeywordModifierTerms = ({
    modifiers,
    baselineCitedRate,
}: {
    modifiers: AEOKeywordModifierApi[]
    baselineCitedRate: number | null
}): JSX.Element => (
    <LemonTable<AEOKeywordModifierApi>
        size="small"
        embedded
        dataSource={modifiers}
        rowKey="term"
        rowStatus={(modifier) => (isCitationGap(modifier, baselineCitedRate) ? 'highlighted' : null)}
        columns={[
            {
                title: 'Word',
                key: 'term',
                render: (_, modifier) => <span className="font-semibold">{modifier.term}</span>,
            },
            {
                title: 'Answers',
                key: 'share',
                align: 'right',
                tooltip: 'Share of answers whose searches used this word.',
                render: (_, modifier) => (
                    <span className="tabular-nums">
                        {percentage(modifier.share, 0)} <span className="text-muted">({modifier.answers})</span>
                    </span>
                ),
            },
            {
                title: 'Cited',
                key: 'cited_rate',
                align: 'right',
                tooltip: 'How often those answers cite your site, against all answers.',
                render: (_, modifier) => (
                    <span className="flex items-center justify-end gap-2 tabular-nums">
                        {isCitationGap(modifier, baselineCitedRate) ? (
                            <LemonTag type="danger" size="small">
                                Gap
                            </LemonTag>
                        ) : null}
                        {modifier.cited_rate === null ? '-' : percentage(modifier.cited_rate, 0)}
                        {baselineCitedRate !== null ? (
                            <span className="text-muted">vs {percentage(baselineCitedRate, 0)}</span>
                        ) : null}
                    </span>
                ),
            },
            {
                title: 'Engines',
                key: 'engines',
                render: (_, modifier) => (
                    <span className="text-muted">
                        {modifier.engines.map((engine) => `${engineLabel(engine.engine)} ${engine.answers}`).join(', ')}
                    </span>
                ),
            },
            {
                title: 'Example searches',
                key: 'example_searches',
                render: (_, modifier) => (
                    <ul className="m-0 flex flex-col gap-0.5 max-w-120">
                        {modifier.example_searches.map((search) => (
                            <li key={search} className="truncate text-xs" title={search}>
                                {search}
                            </li>
                        ))}
                    </ul>
                ),
            },
        ]}
    />
)
