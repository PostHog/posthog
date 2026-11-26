import { Button, Heading, Skeleton, Text } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { AiVisibilityTag } from './AiVisibilityTag'
import type { AnswerMention } from './answerMentions'
import { ContentAutopilotSiteLabel } from './ContentAutopilotSiteLabel'

export type CompetitorCatalogState = 'loading' | 'failed' | 'ready'

/** The brands one answer names, in the order it names them, with whether it also linked to each brand's site.
 *  Competitors come from the brand catalog, so the list waits for it and says when it couldn't load. */
export const ContentAutopilotAnswerMentionList = ({
    mentions,
    competitors,
    onRetryCompetitors,
}: {
    mentions: AnswerMention[]
    competitors: CompetitorCatalogState
    onRetryCompetitors: () => void
}): JSX.Element => (
    <div className="flex flex-col gap-2" data-attr="content-autopilot-prompt-answer-mentions">
        <Heading size="sm" render={<h5 className="m-0" />}>
            Brands in this answer{competitors === 'loading' ? '' : ` (${mentions.length})`}
        </Heading>
        {competitors === 'failed' ? (
            <Text size="xs" variant="muted" className="m-0">
                Couldn't load your competitors, so only your brand is marked.{' '}
                <Button
                    variant="link"
                    size="inline"
                    onClick={onRetryCompetitors}
                    data-attr="content-autopilot-prompt-answer-competitors-retry"
                >
                    Try again
                </Button>
            </Text>
        ) : null}
        {competitors === 'loading' ? (
            <div className="flex flex-col gap-1.5">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-4 w-32" />
            </div>
        ) : mentions.length ? (
            <ol className="m-0 p-0 list-none flex flex-col gap-1.5 text-xs">
                {mentions.map(({ brand, count, cited }, index) => (
                    <li key={brand.key} className="flex flex-wrap items-center justify-between gap-2">
                        <span className="flex min-w-0 items-center gap-2">
                            <span className="w-4 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
                                {index + 1}
                            </span>
                            {brand.domain ? (
                                <ContentAutopilotSiteLabel domain={brand.domain} isTarget={false} isCompetitor>
                                    {brand.name}
                                </ContentAutopilotSiteLabel>
                            ) : (
                                <span className="flex items-center gap-1.5">
                                    <span className="font-semibold">{brand.name}</span>
                                    <AiVisibilityTag type="success">You</AiVisibilityTag>
                                </span>
                            )}
                        </span>
                        <span className="flex items-center gap-2 text-xs text-muted-foreground whitespace-nowrap">
                            {pluralize(count, 'mention')}
                            {cited ? <AiVisibilityTag type="highlight">Cited</AiVisibilityTag> : null}
                        </span>
                    </li>
                ))}
            </ol>
        ) : (
            <Text size="xs" variant="muted" className="m-0">
                This answer names neither your brand nor a confirmed competitor.
            </Text>
        )}
    </div>
)
