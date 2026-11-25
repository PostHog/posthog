import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { pluralize } from 'lib/utils/strings'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { ContentAutopilotCitationsActions } from './ContentAutopilotCitationsActions'
import { type CitationsLookup, contentAutopilotCitationsModalLogic } from './contentAutopilotCitationsModalLogic'
import { ContentAutopilotCitationsTable } from './ContentAutopilotCitationsTable'
import { QuillContentAutopilotCitationsModal } from './QuillContentAutopilotCitationsModal'
import { segmentPrompts } from './utils'

/** The lookup's window in words, such as "Last 90 days" or "October 18 - November 17, 2026". */
const lookupRange = ({ dateFrom, dateTo }: CitationsLookup): string =>
    dateFilterToText(dateFrom, dateTo, null, undefined, true) ?? `${dateFrom} to ${dateTo ?? 'today'}`

const modalTitle = ({ kind, value }: CitationsLookup): string =>
    kind === 'domain'
        ? `Answers that cite ${value}`
        : kind === 'url'
          ? 'Answers that cite this page'
          : `Answers that searched for "${value}"`

/** The answers behind the cited page, cited site or engine search picked anywhere on the AI visibility page. */
export const ContentAutopilotCitationsModal = (): JSX.Element => {
    const { lookup, citations, citationsLoading, citationsFailed, hasMoreCitations, isOwnPage } = useValues(
        contentAutopilotCitationsModalLogic
    )
    const { closeCitations, loadCitations, loadMoreCitations, openCitationPrompt } = useActions(
        contentAutopilotCitationsModalLogic
    )
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const title = lookup ? modalTitle(lookup) : ''
    const description = lookup
        ? `Answers to ${segmentPrompts(lookup.branded)}, newest first. Date range: ${lookupRange(lookup)}.`
        : undefined
    const content = lookup ? (
        <div className="flex flex-col gap-3" data-attr="content-autopilot-citations-modal">
            <ContentAutopilotCitationsActions lookup={lookup} isOwnPage={isOwnPage} />
            {citationsFailed && !citations ? (
                <AiVisibilityBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadCitations, loading: citationsLoading }}
                >
                    Couldn't load the answers. Try again, and if it keeps happening contact support.
                </AiVisibilityBanner>
            ) : (
                <>
                    {citations ? (
                        <span className={todayRailNav ? 'text-xs text-muted-foreground' : 'text-xs text-muted'}>
                            {pluralize(citations.count, 'answer')}
                        </span>
                    ) : null}
                    <ContentAutopilotCitationsTable
                        citations={citations?.results ?? []}
                        loading={citationsLoading && !citations}
                        onOpenPrompt={openCitationPrompt}
                    />
                    {hasMoreCitations ? (
                        <div className="flex justify-center">
                            {todayRailNav ? (
                                <Button
                                    variant="outline"
                                    onClick={loadMoreCitations}
                                    loading={citationsLoading}
                                    data-attr="content-autopilot-citations-load-more"
                                >
                                    Show more answers
                                </Button>
                            ) : (
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    onClick={loadMoreCitations}
                                    loading={citationsLoading}
                                    data-attr="content-autopilot-citations-load-more"
                                >
                                    Show more answers
                                </LemonButton>
                            )}
                        </div>
                    ) : null}
                    {citationsFailed && citations ? (
                        <span className={todayRailNav ? 'text-xs text-destructive-foreground' : 'text-xs text-danger'}>
                            Couldn't load more answers. Try again, and if it keeps happening contact support.
                        </span>
                    ) : null}
                </>
            )}
        </div>
    ) : null

    if (todayRailNav) {
        return (
            <QuillContentAutopilotCitationsModal
                open={!!lookup}
                title={title}
                description={description}
                onClose={closeCitations}
            >
                {content}
            </QuillContentAutopilotCitationsModal>
        )
    }

    return (
        <LemonModal isOpen={!!lookup} onClose={closeCitations} title={title} description={description} width={960}>
            {content}
        </LemonModal>
    )
}
