import { BindLogic, useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import {
    Button,
    Skeleton,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AiVisibilityTag } from './AiVisibilityTag'
import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import {
    type ContentAutopilotSearchDetailLogicProps,
    type SearchDetailTab,
    contentAutopilotSearchDetailLogic,
} from './contentAutopilotSearchDetailLogic'
import { ContentAutopilotSiteLabel } from './ContentAutopilotSiteLabel'

const SHARE_GRID = 'grid list-none grid-cols-[minmax(0,1fr)_minmax(8rem,40%)] items-center gap-3'

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
        <SearchDetail branded={props.branded} engine={props.engine} topic={props.topic} onOpenPrompt={onOpenPrompt} />
    </BindLogic>
)

const SearchDetail = ({
    branded,
    engine,
    topic,
    onOpenPrompt,
}: Pick<ContentAutopilotSearchDetailLogicProps, 'branded' | 'engine' | 'topic'> & {
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

    const lookupWindow = { dateFrom: detail.window_from, dateTo: detail.window_to, branded, engine, topic }
    return (
        <div className="flex flex-col gap-2 px-3 py-2" data-attr="content-autopilot-search-detail">
            <div className="flex flex-wrap items-center gap-1">
                <LabelledChip label="Answers">{humanFriendlyNumber(detail.answers)}</LabelledChip>
                <LabelledChip label="Prompts">{humanFriendlyNumber(detail.prompts)}</LabelledChip>
                {detail.keywords.map((keyword) => (
                    <LabelledChip key={keyword} label="Keyword">
                        {keyword}
                    </LabelledChip>
                ))}
            </div>
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
                        <ul className="m-0 flex flex-col gap-1 p-0">
                            <ShareHeader
                                label="Site"
                                tooltip="Share of the answers that ran this search and cited the site. Answers usually run several searches, so the site can come from another search in the same answer."
                            />
                            {detail.domains.map((domain) => (
                                <ShareRow key={domain.domain} share={domain.share_of_answers}>
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
                    )}
                </TabsContent>
                <TabsContent value="searches">
                    {detail.related_searches.length === 0 ? (
                        <EmptyLine>The answers that ran this search ran no other search.</EmptyLine>
                    ) : (
                        <ul className="m-0 flex flex-col gap-1 p-0">
                            <ShareHeader
                                label="Search"
                                tooltip="Share of the answers that ran this search and also ran the other one."
                            />
                            {detail.related_searches.map((related) => (
                                <ShareRow key={related.query} share={related.share_of_answers}>
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

const ShareHeader = ({ label, tooltip }: { label: string; tooltip: string }): JSX.Element => (
    <li className={`${SHARE_GRID} text-xs text-muted-foreground`}>
        <span>{label}</span>
        <span className="inline-flex items-center gap-1">
            Share of answers
            <Tooltip>
                <TooltipTrigger delay={0} render={<span aria-label={tooltip} />}>
                    <IconInfo />
                </TooltipTrigger>
                <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
            </Tooltip>
        </span>
    </li>
)

const LabelledChip = ({ label, children }: { label: string; children: React.ReactNode }): JSX.Element => (
    <AiVisibilityTag>
        <span className="text-muted-foreground">{label}</span> {children}
    </AiVisibilityTag>
)

const ShareRow = ({ share, children }: { share: number; children: React.ReactNode }): JSX.Element => (
    <li className={SHARE_GRID}>
        <span className="flex min-w-0">{children}</span>
        <ContentAutopilotRateBar rate={share} />
    </li>
)

const EmptyLine = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <Text size="xs" variant="muted" className="m-0 py-1">
        {children}
    </Text>
)
