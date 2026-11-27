import { BindLogic, useActions, useValues } from 'kea'

import { Button, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger, Text } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { AiVisibilityTag } from './AiVisibilityTag'
import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import {
    type ContentAutopilotSearchDetailLogicProps,
    type SearchDetailTab,
    contentAutopilotSearchDetailLogic,
} from './contentAutopilotSearchDetailLogic'
import { ContentAutopilotSiteLabel } from './ContentAutopilotSiteLabel'

const TABS: { key: SearchDetailTab; label: string }[] = [
    { key: 'sites', label: 'Cited sites' },
    { key: 'searches', label: 'Related searches' },
    { key: 'prompts', label: 'Prompts' },
]

/** What one search of the overview tells: the sites its answers cite, the searches that come with it,
 *  the tracked keywords in it and the prompts it came from. */
export const ContentAutopilotSearchDetail = ({
    onOpenPrompt,
    ...props
}: ContentAutopilotSearchDetailLogicProps & { onOpenPrompt: (promptId: string) => void }): JSX.Element => (
    <BindLogic logic={contentAutopilotSearchDetailLogic} props={props}>
        <SearchDetail branded={props.branded} onOpenPrompt={onOpenPrompt} />
    </BindLogic>
)

const SearchDetail = ({
    branded,
    onOpenPrompt,
}: Pick<ContentAutopilotSearchDetailLogicProps, 'branded'> & {
    onOpenPrompt: (promptId: string) => void
}): JSX.Element => {
    const { detail, detailLoading, detailFailed, tab } = useValues(contentAutopilotSearchDetailLogic)
    const { setTab, loadDetail } = useActions(contentAutopilotSearchDetailLogic)

    if (detailLoading && !detail) {
        return (
            <div className="flex flex-col gap-2 px-3 py-2" data-attr="content-autopilot-search-detail-loading">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-24 w-full" />
            </div>
        )
    }
    if (detailFailed || !detail) {
        return (
            <div className="flex items-center gap-2 px-3 py-2">
                <Text size="xs" variant="muted" className="m-0">
                    Couldn't load this search.
                </Text>
                <Button
                    variant="link"
                    size="inline"
                    onClick={loadDetail}
                    data-attr="content-autopilot-search-detail-retry"
                >
                    Try again
                </Button>
            </div>
        )
    }

    const lookupWindow = { dateFrom: detail.window_from, dateTo: detail.window_to, branded }
    return (
        <div className="flex flex-col gap-2 px-3 py-2" data-attr="content-autopilot-search-detail">
            <Text size="xs" variant="muted" className="m-0">
                Ran in {pluralize(detail.answers, 'answer')} on {pluralize(detail.prompts, 'prompt')}.{' '}
                {detail.target_rank
                    ? `Your site is #${detail.target_rank} of ${pluralize(detail.domains_cited, 'cited site')}.`
                    : 'Your site was not cited in these answers.'}
            </Text>
            {detail.keywords.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    <Text size="xs" variant="muted" className="m-0">
                        Tracked keywords:
                    </Text>
                    {detail.keywords.map((keyword) => (
                        <AiVisibilityTag key={keyword}>{keyword}</AiVisibilityTag>
                    ))}
                </div>
            )}
            <Tabs value={tab} onValueChange={(value: SearchDetailTab) => setTab(value)}>
                <TabsList variant="line">
                    {TABS.map(({ key, label }) => (
                        <TabsTrigger key={key} value={key} data-attr={`content-autopilot-search-detail-tab-${key}`}>
                            {label}
                        </TabsTrigger>
                    ))}
                </TabsList>
                <TabsContent value="sites">
                    {detail.domains.length === 0 ? (
                        <EmptyLine>No answer that ran this search cited a site.</EmptyLine>
                    ) : (
                        <>
                            <ul className="m-0 flex flex-col gap-1 p-0">
                                {detail.domains.map((domain) => (
                                    <ShareRow
                                        key={domain.domain}
                                        share={domain.share_of_answers}
                                        tooltip={`Cited in ${pluralize(domain.answers, 'answer')} of ${detail.answers}`}
                                    >
                                        <ContentAutopilotSiteLabel domain={domain.domain} isTarget={domain.is_target}>
                                            <ContentAutopilotCitationsLink
                                                lookup={{ kind: 'domain', value: domain.domain, ...lookupWindow }}
                                                source="overview-search-detail-sites"
                                            >
                                                {domain.domain}
                                            </ContentAutopilotCitationsLink>
                                        </ContentAutopilotSiteLabel>
                                    </ShareRow>
                                ))}
                            </ul>
                            <Text size="xs" variant="muted" className="m-0 mt-2">
                                Share of the answers that ran this search and cited the site. Answers usually run
                                several searches, so a site can come from another search in the same answer.
                            </Text>
                        </>
                    )}
                </TabsContent>
                <TabsContent value="searches">
                    {detail.related_searches.length === 0 ? (
                        <EmptyLine>The answers that ran this search ran no other search.</EmptyLine>
                    ) : (
                        <ul className="m-0 flex flex-col gap-1 p-0">
                            {detail.related_searches.map((related) => (
                                <ShareRow
                                    key={related.query}
                                    share={related.share_of_answers}
                                    tooltip={`Ran together in ${pluralize(related.answers, 'answer')} of ${detail.answers}`}
                                >
                                    <ContentAutopilotCitationsLink
                                        lookup={{ kind: 'search', value: related.query, ...lookupWindow }}
                                        source="overview-search-detail-searches"
                                        title={related.query}
                                    >
                                        {related.query}
                                    </ContentAutopilotCitationsLink>
                                </ShareRow>
                            ))}
                        </ul>
                    )}
                </TabsContent>
                <TabsContent value="prompts">
                    <Text size="xs" variant="muted" className="m-0 mb-1">
                        {detail.prompts > detail.top_prompts.length
                            ? `Top ${detail.top_prompts.length} of ${pluralize(detail.prompts, 'prompt')} that ran this search`
                            : 'Prompts that ran this search'}
                    </Text>
                    <ul className="m-0 flex flex-col gap-1 p-0">
                        {detail.top_prompts.map((prompt) => (
                            <li key={prompt.id} className="list-none">
                                {/* A prompt is a sentence, so the link wraps instead of truncating. */}
                                <Button
                                    variant="link-foreground"
                                    size="inline"
                                    onClick={() => onOpenPrompt(prompt.id)}
                                    className="whitespace-normal text-left"
                                    data-attr="content-autopilot-prompts-overview-search-prompt"
                                >
                                    {prompt.text}
                                </Button>
                            </li>
                        ))}
                    </ul>
                </TabsContent>
            </Tabs>
        </div>
    )
}

const ShareRow = ({
    share,
    tooltip,
    children,
}: {
    share: number
    tooltip: string
    children: React.ReactNode
}): JSX.Element => (
    <li className="grid list-none grid-cols-[minmax(0,1fr)_minmax(8rem,40%)] items-center gap-3">
        <span className="flex min-w-0">{children}</span>
        <ContentAutopilotRateBar rate={share} tooltip={tooltip} />
    </li>
)

const EmptyLine = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <Text size="xs" variant="muted" className="m-0 py-1">
        {children}
    </Text>
)
