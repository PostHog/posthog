import { IconExternal } from '@posthog/icons'
import { Button, Progress, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { percentage } from 'lib/utils/numbers'

import type { QueryContext, QueryContextColumnComponent } from '~/queries/types'

import { AiVisibilityTag } from './AiVisibilityTag'
import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { CITATIONS_MAX_DATE_FROM, type CitationsLookup } from './contentAutopilotCitationsModalLogic'
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
    dateFrom: CITATIONS_MAX_DATE_FROM,
    dateTo: null,
    branded: 'all',
})

const TargetTag = (): JSX.Element => (
    <AiVisibilityTag type="success" className="shrink-0">
        Your site
    </AiVisibilityTag>
)

const DomainCell: QueryContextColumnComponent = ({ value, record }) => {
    const domain = String(value ?? '')
    return (
        <span className="flex items-center gap-2 min-w-0">
            <Tooltip>
                <TooltipTrigger render={<span className="min-w-0 max-w-56 truncate" />}>
                    <ContentAutopilotCitationsLink lookup={lookupFor('domain', domain)} source="prompt-sources-tile">
                        {domain}
                    </ContentAutopilotCitationsLink>
                </TooltipTrigger>
                <TooltipContent>{domain}</TooltipContent>
            </Tooltip>
            {cellAt(record, PROMPT_SOURCE_COLUMNS, 'is_target') ? <TargetTag /> : null}
        </span>
    )
}

const UrlCell: QueryContextColumnComponent = ({ value, record }) => {
    const url = String(value ?? '')
    return (
        <span className="flex flex-wrap items-center gap-2 min-w-0">
            <ContentAutopilotCitationsLink lookup={lookupFor('url', url)} source="prompt-citations-tile">
                {url}
            </ContentAutopilotCitationsLink>
            {isWebUrl(url) ? (
                <Button
                    size="icon-sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={url} target="_blank" />}
                    aria-label="Open the page"
                    tooltip="Open the page"
                    data-attr="content-autopilot-prompt-citations-tile-open"
                >
                    <IconExternal />
                </Button>
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
            <Progress value={share * 100} aria-label="Share of all answers" className="flex-1" />
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
