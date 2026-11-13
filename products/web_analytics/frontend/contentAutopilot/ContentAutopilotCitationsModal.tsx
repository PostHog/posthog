import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { ContentAutopilotCitationsActions } from './ContentAutopilotCitationsActions'
import { type CitationsLookup, contentAutopilotCitationsModalLogic } from './contentAutopilotCitationsModalLogic'
import { ContentAutopilotCitationsTable } from './ContentAutopilotCitationsTable'
import { segmentPrompts } from './utils'

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

    return (
        <LemonModal
            isOpen={!!lookup}
            onClose={closeCitations}
            title={lookup ? modalTitle(lookup) : ''}
            description={
                lookup
                    ? `Answers to ${segmentPrompts(lookup.branded)} over the last ${lookup.days} days, newest first.`
                    : undefined
            }
            width={960}
        >
            {lookup ? (
                <div className="flex flex-col gap-3" data-attr="content-autopilot-citations-modal">
                    <ContentAutopilotCitationsActions lookup={lookup} isOwnPage={isOwnPage} />
                    {citationsFailed && !citations ? (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Try again', onClick: loadCitations, loading: citationsLoading }}
                        >
                            Couldn't load the answers. Try again, and if it keeps happening contact support.
                        </LemonBanner>
                    ) : (
                        <>
                            {citations ? (
                                <span className="text-xs text-muted">{pluralize(citations.count, 'answer')}</span>
                            ) : null}
                            <ContentAutopilotCitationsTable
                                citations={citations?.results ?? []}
                                loading={citationsLoading && !citations}
                                onOpenPrompt={openCitationPrompt}
                            />
                            {hasMoreCitations ? (
                                <div className="flex justify-center">
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        onClick={loadMoreCitations}
                                        loading={citationsLoading}
                                        data-attr="content-autopilot-citations-load-more"
                                    >
                                        Show more answers
                                    </LemonButton>
                                </div>
                            ) : null}
                            {citationsFailed && citations ? (
                                <span className="text-xs text-danger">
                                    Couldn't load more answers. Try again, and if it keeps happening contact support.
                                </span>
                            ) : null}
                        </>
                    )}
                </div>
            ) : null}
        </LemonModal>
    )
}
