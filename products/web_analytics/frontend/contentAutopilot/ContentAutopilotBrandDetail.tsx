import { useActions, useValues } from 'kea'

import { Button, Tabs, TabsContent, TabsList, TabsTrigger, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AI_VISIBILITY_TAB_FILTERS } from './aiVisibilityFilters'
import { AiVisibilityTag } from './AiVisibilityTag'
import { brandKindTag } from './brandDetail'
import { ContentAutopilotBrandCitedSites } from './ContentAutopilotBrandCitedSites'
import { type BrandDetailTab, contentAutopilotBrandDetailLogic } from './contentAutopilotBrandDetailLogic'
import { ContentAutopilotBrandDetailSkeleton } from './ContentAutopilotBrandDetailSkeleton'
import { ContentAutopilotBrandKpis } from './ContentAutopilotBrandKpis'
import { ContentAutopilotBrandPicker } from './ContentAutopilotBrandPicker'
import { ContentAutopilotBrandPrompts } from './ContentAutopilotBrandPrompts'
import { ContentAutopilotBrandSearches } from './ContentAutopilotBrandSearches'
import { ContentAutopilotBrandSentiment } from './ContentAutopilotBrandSentiment'
import { ContentAutopilotFilterBar } from './ContentAutopilotFilterBar'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotPageHeader } from './ContentAutopilotPageHeader'
import { ContentAutopilotPromptsDisabled } from './ContentAutopilotPromptsDisabled'

const TABS: { key: BrandDetailTab; label: string }[] = [
    { key: 'prompts', label: 'Prompts' },
    { key: 'citations', label: 'Citations' },
    { key: 'sentiment', label: 'Sentiment' },
    { key: 'searches', label: 'Searches' },
]

/** One catalog brand's page, on its own URL in place of the workspace tabs. */
export const ContentAutopilotBrandDetail = (): JSX.Element | null => {
    const { brandId, detail, detailLoading, detailError, kpis, pickerGroups, tab } = useValues(
        contentAutopilotBrandDetailLogic
    )
    const { openBrandDetail, loadDetail, setTab, openBrandPrompt } = useActions(contentAutopilotBrandDetailLogic)
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)
    const backToRankings = (): void => setWorkspaceTab('rankings')

    if (!brandId) {
        return null
    }
    if (detailError === 'forbidden') {
        return <ContentAutopilotPromptsDisabled />
    }
    if (detailError === 'not_found') {
        return (
            <div className="flex flex-col gap-4" data-attr="content-autopilot-brand-page">
                <ContentAutopilotPageHeader
                    title="Brand not found"
                    backLabel="Rankings"
                    backDataAttr="content-autopilot-brand-back"
                    onBack={backToRankings}
                />
                <Text size="xs" className="m-0">
                    This brand isn't in the project's brand catalog, or the link is wrong.
                </Text>
            </div>
        )
    }

    const tag = detail ? brandKindTag(detail.brand.kind) : null
    return (
        <div className="flex flex-col gap-4" data-attr="content-autopilot-brand-page">
            <ContentAutopilotPageHeader
                title={detail?.brand.name ?? (detailError === 'failed' ? 'Brand' : 'Loading brand')}
                backLabel="Rankings"
                backDataAttr="content-autopilot-brand-back"
                onBack={backToRankings}
                actions={
                    pickerGroups.length > 0 ? (
                        <ContentAutopilotBrandPicker
                            brandId={brandId}
                            groups={pickerGroups}
                            onChange={openBrandDetail}
                        />
                    ) : null
                }
            />
            <ContentAutopilotFilterBar tab="brand" filters={AI_VISIBILITY_TAB_FILTERS.brand} />
            {detailError === 'failed' ? (
                <AiVisibilityBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadDetail, loading: detailLoading }}
                >
                    Couldn't load this brand. Try again, and if it keeps happening contact support.
                </AiVisibilityBanner>
            ) : !detail || !kpis ? (
                <ContentAutopilotBrandDetailSkeleton />
            ) : (
                <div
                    className={detailLoading ? 'flex flex-col gap-4 opacity-50' : 'flex flex-col gap-4'}
                    aria-busy={detailLoading}
                >
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        {detail.domains.map((domain) => (
                            <Button
                                key={domain}
                                variant="link-foreground"
                                size="inline"
                                nativeButton={false}
                                render={<LinkPrimitive to={`https://${domain}`} target="_blank" />}
                                data-attr="content-autopilot-brand-domain"
                            >
                                {domain}
                            </Button>
                        ))}
                        {tag ? <AiVisibilityTag type={tag.type}>{tag.label}</AiVisibilityTag> : null}
                    </div>
                    <ContentAutopilotBrandKpis kpis={kpis} />
                    <Tabs
                        value={tab}
                        onValueChange={(next: BrandDetailTab) => setTab(next)}
                        data-attr="content-autopilot-brand-tabs"
                    >
                        <div className="overflow-x-auto">
                            <TabsList variant="line">
                                {TABS.map(({ key, label }) => (
                                    <TabsTrigger key={key} value={key} data-attr={`content-autopilot-brand-tab-${key}`}>
                                        {label}
                                    </TabsTrigger>
                                ))}
                            </TabsList>
                        </div>
                        <TabsContent value="prompts">
                            <ContentAutopilotBrandPrompts prompts={detail.prompts} onOpenPrompt={openBrandPrompt} />
                        </TabsContent>
                        <TabsContent value="citations">
                            <ContentAutopilotBrandCitedSites
                                sites={detail.cited_sites}
                                dateFrom={detail.window_from}
                                dateTo={detail.window_to}
                                branded={detail.branded}
                                engine={detail.engine}
                                topic={detail.topic}
                            />
                        </TabsContent>
                        <TabsContent value="sentiment">
                            <ContentAutopilotBrandSentiment
                                sentiment={detail.sentiment}
                                onOpenPrompt={openBrandPrompt}
                            />
                        </TabsContent>
                        <TabsContent value="searches">
                            <ContentAutopilotBrandSearches
                                searches={detail.searches}
                                dateFrom={detail.window_from}
                                dateTo={detail.window_to}
                                branded={detail.branded}
                                engine={detail.engine}
                                topic={detail.topic}
                                onOpenPrompt={openBrandPrompt}
                            />
                        </TabsContent>
                    </Tabs>
                </div>
            )}
        </div>
    )
}
