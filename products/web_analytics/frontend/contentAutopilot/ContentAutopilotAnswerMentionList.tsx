import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type { AnswerMention } from './answerMentions'
import { ContentAutopilotSiteLabel } from './ContentAutopilotSiteLabel'

export type CompetitorCatalogState = 'loading' | 'failed' | 'ready'

/** The brands one answer names, in the order it names them, with whether it also linked to each brand's site.
 *  Competitors come from the brand catalog, so the list waits for it and says when it couldn't load. */
export const ContentAutopilotAnswerMentionList = ({
    mentions,
    competitors,
}: {
    mentions: AnswerMention[]
    competitors: CompetitorCatalogState
}): JSX.Element => (
    <div className="flex flex-col gap-2" data-attr="content-autopilot-prompt-answer-mentions">
        <h5 className="m-0">Brands in this answer{competitors === 'loading' ? '' : ` (${mentions.length})`}</h5>
        {competitors === 'failed' ? (
            <span className="text-muted text-sm">
                Couldn't load your competitors, so only your brand is marked. Refresh the page to try again.
            </span>
        ) : null}
        {competitors === 'loading' ? (
            <div className="flex flex-col gap-1.5">
                <LemonSkeleton className="h-4 w-40" />
                <LemonSkeleton className="h-4 w-32" />
            </div>
        ) : mentions.length ? (
            <ol className="m-0 p-0 list-none flex flex-col gap-1.5 text-sm">
                {mentions.map(({ brand, count, cited }, index) => (
                    <li key={brand.key} className="flex flex-wrap items-center justify-between gap-2">
                        <span className="flex min-w-0 items-center gap-2">
                            <span className="w-4 shrink-0 text-right text-xs text-muted tabular-nums">{index + 1}</span>
                            {brand.domain ? (
                                <ContentAutopilotSiteLabel domain={brand.domain} isTarget={false} isCompetitor>
                                    {brand.name}
                                </ContentAutopilotSiteLabel>
                            ) : (
                                <span className="flex items-center gap-1.5">
                                    <span className="font-semibold">{brand.name}</span>
                                    <LemonTag type="success" size="small">
                                        You
                                    </LemonTag>
                                </span>
                            )}
                        </span>
                        <span className="flex items-center gap-2 text-xs text-secondary whitespace-nowrap">
                            {pluralize(count, 'mention')}
                            {cited ? (
                                <LemonTag type="highlight" size="small">
                                    Cited
                                </LemonTag>
                            ) : null}
                        </span>
                    </li>
                ))}
            </ol>
        ) : (
            <span className="text-muted text-sm">This answer names neither your brand nor a confirmed competitor.</span>
        )}
    </div>
)
