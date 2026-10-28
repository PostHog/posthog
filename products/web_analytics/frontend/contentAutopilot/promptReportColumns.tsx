import { LemonTag, Link } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { percentage } from 'lib/utils/numbers'

import type { QueryContext, QueryContextColumnComponent } from '~/queries/types'

import { PROMPT_CITATION_COLUMNS, PROMPT_SOURCE_COLUMNS } from './promptReportQueries'

// Engine output is third-party text: only plain http(s) URLs become links.
const isWebUrl = (url: string): boolean => /^https?:\/\//i.test(url)

/** HogQL rows reach the column renderers as arrays, so a renderer that needs a sibling column looks it up by position. */
const cellAt = (record: unknown, columns: readonly string[], name: string): unknown =>
    Array.isArray(record) ? record[columns.indexOf(name)] : undefined

const TargetTag = (): JSX.Element => (
    <LemonTag type="success" size="small">
        Your site
    </LemonTag>
)

const DomainCell: QueryContextColumnComponent = ({ value, record }) => (
    <span className="flex flex-wrap items-center gap-2">
        <span className="break-all">{String(value ?? '')}</span>
        {cellAt(record, PROMPT_SOURCE_COLUMNS, 'is_target') ? <TargetTag /> : null}
    </span>
)

const UrlCell: QueryContextColumnComponent = ({ value, record }) => {
    const url = String(value ?? '')
    return (
        <span className="flex flex-wrap items-center gap-2 min-w-0">
            {isWebUrl(url) ? (
                <Link to={url} target="_blank" className="break-all">
                    {url}
                </Link>
            ) : (
                <span className="break-all">{url}</span>
            )}
            {cellAt(record, PROMPT_CITATION_COLUMNS, 'is_target') ? <TargetTag /> : null}
        </span>
    )
}

const ShareCell: QueryContextColumnComponent = ({ value }) => {
    const share = typeof value === 'number' ? value : Number(value ?? 0)
    return (
        <span className="flex items-center gap-2 min-w-32">
            <LemonProgress percent={share * 100} className="flex-1" />
            <span className="w-10 text-right tabular-nums">{percentage(share, 0)}</span>
        </span>
    )
}

const sharedColumns: QueryContext['columns'] = {
    answers: { title: 'Answers that link to it', align: 'right' },
    share_of_answers: { title: 'Share of all answers', render: ShareCell, align: 'right', width: 180 },
    is_target: { hidden: true },
}

export const promptSourcesContext: QueryContext = {
    showQueryEditor: false,
    columns: { ...sharedColumns, domain: { title: 'Site', render: DomainCell } },
}

export const promptCitationsContext: QueryContext = {
    showQueryEditor: false,
    columns: { ...sharedColumns, url: { title: 'Page', render: UrlCell } },
}

export const promptSearchesContext: QueryContext = {
    showQueryEditor: false,
    columns: {
        query: { title: 'Search' },
        searches: { title: 'Times run', align: 'right' },
        engines: { title: 'Engines that ran it', align: 'right' },
    },
}
