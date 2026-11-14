import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import { ContentAutopilotKeywordModifierTerms } from './ContentAutopilotKeywordModifierTerms'
import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { type ModifierGroup, isCitationGap, modifierGroups } from './keywordsReport'

export const ContentAutopilotKeywordModifiers = (): JSX.Element => {
    const { modifiers, modifiersLoading, modifiersError, modifierKeyword, keywords } =
        useValues(contentAutopilotKeywordsLogic)
    const { loadModifiers, setModifierKeyword } = useActions(contentAutopilotKeywordsLogic)

    return (
        <PagePerformanceCard className="min-w-0">
            <PagePerformanceCardHeader title="What the engines add to your searches" />
            <div className="flex flex-col gap-3 p-3" data-attr="content-autopilot-keywords-modifiers">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="m-0 text-xs text-muted max-w-2xl">
                        Words the engines put in their web searches that your prompts don't contain, such as a year,
                        "pricing" or "vs". Each points at content the engines look for. Words whose answers cite you
                        much less than usual are marked as gaps.
                    </p>
                    <LemonSelect<string | null>
                        size="small"
                        aria-label="Keyword filter"
                        value={modifierKeyword}
                        onChange={setModifierKeyword}
                        options={[
                            { value: null, label: 'All searches' },
                            ...(keywords ?? []).map((keyword) => ({
                                value: keyword.keyword,
                                label: `Searches with "${keyword.keyword}"`,
                            })),
                        ]}
                        data-attr="content-autopilot-keywords-modifier-filter"
                    />
                </div>
                {modifiersError ? (
                    <LemonBanner
                        type="error"
                        action={{ children: 'Try again', onClick: loadModifiers, loading: modifiersLoading }}
                    >
                        Couldn't load the search words. Try again, and if it keeps happening contact support.
                    </LemonBanner>
                ) : !modifiers ? (
                    <LemonSkeleton className="h-24" />
                ) : modifiers.modifiers.length === 0 ? (
                    <p className="m-0 text-muted" data-attr="content-autopilot-keywords-modifiers-empty">
                        {modifiers.answers === 0
                            ? `No answers ${modifierKeyword ? `searched for "${modifierKeyword}" ` : ''}in the last ${modifiers.days} days.`
                            : 'The engines searched only for words your prompts already contain. Only some engines report the searches they run.'}
                    </p>
                ) : (
                    <LemonTable<ModifierGroup>
                        size="small"
                        dataSource={modifierGroups(modifiers.modifiers)}
                        rowKey="kind"
                        loading={modifiersLoading}
                        columns={[
                            {
                                title: 'Group',
                                key: 'label',
                                render: (_, group) => (
                                    <div>
                                        <div className="font-semibold">{group.label}</div>
                                        <div className="text-xs text-muted">{group.description}</div>
                                    </div>
                                ),
                            },
                            {
                                title: 'Words',
                                key: 'modifiers',
                                render: (_, group) => (
                                    <span className="text-muted">
                                        {group.modifiers
                                            .slice(0, 4)
                                            .map((modifier) => modifier.term)
                                            .join(', ')}
                                        {group.modifiers.length > 4 ? ` and ${group.modifiers.length - 4} more` : ''}
                                    </span>
                                ),
                            },
                            {
                                title: 'Gaps',
                                key: 'kind',
                                align: 'right',
                                tooltip: 'Words in the group whose answers cite you much less than usual.',
                                render: (_, group) => {
                                    const gaps = group.modifiers.filter((modifier) =>
                                        isCitationGap(modifier, modifiers.baseline_cited_rate)
                                    ).length
                                    return gaps ? (
                                        <LemonTag type="danger" size="small">
                                            {pluralize(gaps, 'gap')}
                                        </LemonTag>
                                    ) : (
                                        <span className="text-muted">-</span>
                                    )
                                },
                            },
                        ]}
                        expandable={{
                            noIndent: true,
                            expandedRowRender: (group) => (
                                <ContentAutopilotKeywordModifierTerms
                                    modifiers={group.modifiers}
                                    baselineCitedRate={modifiers.baseline_cited_rate}
                                />
                            ),
                        }}
                        footer={
                            <span className="px-3 py-2 text-xs text-muted">
                                Over {pluralize(modifiers.answers, 'answer')} in the last {modifiers.days} days. Your
                                site is cited in{' '}
                                {modifiers.baseline_cited_rate === null
                                    ? '-'
                                    : percentage(modifiers.baseline_cited_rate, 0)}{' '}
                                of them. Expand a group to see its words.
                            </span>
                        }
                    />
                )}
            </div>
        </PagePerformanceCard>
    )
}
