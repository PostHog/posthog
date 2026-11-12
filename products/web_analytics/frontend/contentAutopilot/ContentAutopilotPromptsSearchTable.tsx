import { LemonTable, LemonTableColumn, Link } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { AEOPromptSetSearchApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotEngineMarks } from './ContentAutopilotEngineMarks'
import { OVERVIEW_DAYS } from './contentAutopilotPromptsOverviewLogic'

type SearchRow = AEOPromptSetSearchApi
type SearchColumn = LemonTableColumn<SearchRow, keyof SearchRow | undefined>

const citedShare = (row: SearchRow): number => (row.answers ? row.cited / row.answers : 0)

/** One row per web search the engines ran. Expanding a row lists the prompts that ran it. */
export const ContentAutopilotPromptsSearchTable = ({
    rows,
    onOpenPrompt,
}: {
    rows: SearchRow[]
    onOpenPrompt: (promptId: string) => void
}): JSX.Element => {
    const columns: SearchColumn[] = [
        {
            title: 'Search',
            key: 'query',
            render: (_, row) => (
                <span className="block max-w-120 truncate font-semibold" title={row.query}>
                    {row.query}
                </span>
            ),
        },
        {
            title: 'Prompts',
            key: 'prompts',
            align: 'right',
            tooltip: 'Different prompts whose answers ran this search.',
            sorter: (a, b) => a.prompts - b.prompts,
            render: (_, row) => <span className="tabular-nums">{row.prompts}</span>,
        },
        {
            title: 'Cited',
            key: 'cited',
            align: 'right',
            tooltip: 'How often the answers that ran this search linked to your site.',
            sorter: (a, b) => citedShare(a) - citedShare(b),
            render: (_, row) => (
                <span className="tabular-nums">
                    {percentage(citedShare(row), 0)} <span className="text-muted">of {row.answers}</span>
                </span>
            ),
        },
        {
            title: 'Engines',
            key: 'engines',
            render: (_, row) => <ContentAutopilotEngineMarks engines={row.engines} />,
        },
    ]
    return (
        <LemonTable
            size="small"
            embedded
            dataSource={rows}
            rowKey="query"
            columns={columns}
            expandable={{
                noIndent: true,
                expandedRowRender: (row) => (
                    <div className="px-3 py-2" data-attr="content-autopilot-prompts-overview-search-prompts">
                        <div className="text-xs text-muted mb-1">
                            {row.prompts > row.top_prompts.length
                                ? `Top ${row.top_prompts.length} of ${pluralize(row.prompts, 'prompt')} that ran this search`
                                : 'Prompts that ran this search'}
                        </div>
                        <ul className="m-0 flex flex-col gap-1">
                            {row.top_prompts.map((prompt) => (
                                <li key={prompt.id}>
                                    <Link
                                        onClick={() => onOpenPrompt(prompt.id)}
                                        data-attr="content-autopilot-prompts-overview-search-prompt"
                                    >
                                        {prompt.text}
                                    </Link>
                                </li>
                            ))}
                        </ul>
                    </div>
                ),
            }}
            emptyState={`No web searches in the last ${OVERVIEW_DAYS} days. Only some engines report the searches they run.`}
        />
    )
}
