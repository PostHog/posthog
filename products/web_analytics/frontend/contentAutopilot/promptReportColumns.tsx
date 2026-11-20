import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { percentage } from 'lib/utils/numbers'

import type { QueryContext, QueryContextColumnComponent } from '~/queries/types'

import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { CITATIONS_MAX_DAYS, type CitationsLookup } from './contentAutopilotCitationsModalLogic'
import { PROMPT_CITATION_COLUMNS, PROMPT_SOURCE_COLUMNS } from './promptReportQueries'

// Engine output is third-party text: only plain http(s) URLs become links.
const isWebUrl = (url: string): boolean => /^https?:\/\//i.test(url)

/** HogQL rows reach the column renderers as arrays, so a renderer that needs a sibling column looks it up by position. */
const cellAt = (record: unknown, columns: readonly string[], name: string): unknown =>
    Array.isArray(record) ? record[columns.indexOf(name)] : undefined

// The tiles cover one prompt, and the lookup opens every prompt's answers, so it uses the longest window.
const lookupFor = (kind: CitationsLookup['kind'], value: string): CitationsLookup => ({
    kind,
    value,
    days: CITATIONS_MAX_DAYS,
    branded: 'all',
})

const TargetTag = (): JSX.Element => (
    <LemonTag type="success" size="small" className="shrink-0">
        Your site
    </LemonTag>
)

const DomainCell: QueryContextColumnComponent = ({ value, record }) => {
    const domain = String(value ?? '')
    return (
        <span className="flex items-center gap-2 min-w-0">
            <Tooltip title={domain}>
                <span className="min-w-0 max-w-56 truncate">
                    <ContentAutopilotCitationsLink lookup={lookupFor('domain', domain)} source="prompt-sources-tile">
                        {domain}
                    </ContentAutopilotCitationsLink>
                </span>
            </Tooltip>
            {cellAt(record, PROMPT_SOURCE_COLUMNS, 'is_target') ? <TargetTag /> : null}
        </span>
    )
}

const UrlCell: QueryContextColumnComponent = ({ value, record }) => {
    const url = String(value ?? '')
    return (
        <span className="flex flex-wrap items-center gap-2 min-w-0">
            <ContentAutopilotCitationsLink
                lookup={lookupFor('url', url)}
                source="prompt-citations-tile"
                className="break-all"
            >
                {url}
            </ContentAutopilotCitationsLink>
            {isWebUrl(url) ? (
                <LemonButton
                    size="xsmall"
                    icon={<IconExternal />}
                    to={url}
                    targetBlank
                    hideExternalLinkIcon
                    tooltip="Open the page"
                    data-attr="content-autopilot-prompt-citations-tile-open"
                />
            ) : null}
            {cellAt(record, PROMPT_CITATION_COLUMNS, 'is_target') ? <TargetTag /> : null}
        </span>
    )
}

const SearchCell: QueryContextColumnComponent = ({ value }) => {
    const query = String(value ?? '')
    return (
        <ContentAutopilotCitationsLink lookup={lookupFor('search', query)} source="prompt-searches-tile">
            {query}
        </ContentAutopilotCitationsLink>
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
        query: { title: 'Search', render: SearchCell },
        searches: { title: 'Times run', align: 'right' },
        engines: { title: 'Engines that ran it', align: 'right' },
    },
}
