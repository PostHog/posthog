import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { OverviewMetricCardGrid } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { aiVisibilityFirstResultsLogic } from './aiVisibilityFirstResultsLogic'
import { AiVisibilityTable } from './AiVisibilityTable'
import { AiVisibilityTag } from './AiVisibilityTag'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { ContentAutopilotMetricLabel } from './ContentAutopilotMetricLabel'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import { ShareOfVoiceRow, answeredChecks, firstResultsView } from './firstResults'
import { rateItem } from './metricItems'
import { sortEngines } from './utils'

const FIRST_RESULT_LABELS: Record<string, { label: string; description: string; 'data-attr': string }> = {
    named: {
        label: 'Named in answers',
        description: "Answers to prompts that don't name you, which named your brand or linked to your site.",
        'data-attr': 'ai-visibility-first-results-named',
    },
    cited: {
        label: 'Cited as a source',
        description: "Answers to prompts that don't name you, which linked to a page on your site.",
        'data-attr': 'ai-visibility-first-results-cited',
    },
    branded: {
        label: 'When asked about you',
        description: 'Answers to prompts that name your brand, which linked to your site.',
        'data-attr': 'ai-visibility-first-results-branded',
    },
}

export const AiVisibilityFirstResults = (): JSX.Element => {
    const { firstResults, firstResultsLoading } = useValues(aiVisibilityFirstResultsLogic)
    const { loadFirstResults } = useActions(aiVisibilityFirstResultsLogic)

    if (!firstResults) {
        return firstResultsLoading ? (
            <LemonSkeleton className="h-96 w-full" />
        ) : (
            <AiVisibilityBanner type="error" action={{ children: 'Try again', onClick: loadFirstResults }}>
                Couldn't load your first results. Try again, and if it keeps happening contact support.
            </AiVisibilityBanner>
        )
    }

    const { nonBranded, branded, rankings } = firstResults
    const view = firstResultsView(nonBranded, branded, rankings)
    const brandName = firstResults.ownName || nonBranded.brand_names[0] || 'you'
    const rows = view.brands.map((row) => (row.isYou ? { ...row, name: brandName } : row))
    const engines = sortEngines(nonBranded.engines.map(({ engine }) => engine))
        .map((engine) => nonBranded.engines.find((row) => row.engine === engine))
        .filter((row): row is NonNullable<typeof row> => !!row && answeredChecks(row) > 0)

    return (
        <div data-attr="ai-visibility-first-results">
            <h3 className="m-0">How AI answers see {brandName}</h3>
            <p className="m-0 mt-1 text-muted">
                From {pluralize(view.openAnswers, 'answer')} to prompts that don't name you
                {view.brandedAnswers > 0
                    ? `. "When asked about you" uses the ${pluralize(view.brandedAnswers, 'answer')} to prompts that do.`
                    : '.'}{' '}
                The overview shows trends once the checks have run on more days.
            </p>

            <div className="mt-4" data-attr="ai-visibility-first-results-kpis">
                <OverviewMetricCardGrid
                    className="grid-cols-1 sm:grid-cols-3"
                    loading={false}
                    numSkeletons={3}
                    items={[
                        rateItem('named', { part: view.named, whole: view.openAnswers }, null),
                        rateItem('cited', { part: view.cited, whole: view.openAnswers }, null),
                        rateItem(
                            'branded',
                            { part: view.brandedCited, whole: view.brandedAnswers },
                            null,
                            view.brandedAnswers > 0 ? undefined : 'No prompts name your brand'
                        ),
                    ]}
                    labelFromKey={(key) => <ContentAutopilotMetricLabel {...FIRST_RESULT_LABELS[key]} />}
                />
            </div>

            <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
                <div className="min-w-0 lg:col-span-2">
                    <h4 className="m-0">Brands AI answers name</h4>
                    <p className="m-0 mt-1 mb-2 text-xs text-secondary">
                        Brands named in at least one of the {pluralize(view.openAnswers, 'answer')}, and you.{' '}
                        {rankings.competitors_confirmed
                            ? 'They are the competitors you confirmed.'
                            : 'They are the competitors PostHog suggested. Confirm yours below.'}
                    </p>
                    <AiVisibilityTable<ShareOfVoiceRow>
                        size="small"
                        dataSource={rows}
                        rowKey="domain"
                        data-attr="ai-visibility-first-results-brands"
                        columns={[
                            {
                                title: 'Brand',
                                key: 'brand',
                                render: (_, row) => (
                                    <span className="flex items-center gap-2">
                                        <span className="flex flex-col">
                                            <span className="font-semibold">{row.name}</span>
                                            <span className="text-xs text-secondary">{row.domain}</span>
                                        </span>
                                        {row.isYou ? (
                                            <AiVisibilityTag type="highlight">Your site</AiVisibilityTag>
                                        ) : null}
                                    </span>
                                ),
                            },
                            {
                                title: 'Named in',
                                key: 'visibility',
                                width: '45%',
                                render: (_, row) => <ContentAutopilotRateBar rate={row.visibility} />,
                            },
                        ]}
                    />
                </div>
                <div className="min-w-0">
                    <h4 className="m-0">By engine</h4>
                    <p className="m-0 mt-1 mb-2 text-xs text-secondary">Answers that named you, per engine.</p>
                    <ul
                        className="m-0 flex list-none flex-col gap-2 p-0"
                        data-attr="ai-visibility-first-results-engines"
                    >
                        {engines.map((row) => (
                            <li key={row.engine} className="flex items-center justify-between gap-4">
                                <ContentAutopilotEngineLabel engine={row.engine} />
                                <span className="w-32">
                                    <ContentAutopilotRateBar
                                        rate={row.mentioned / answeredChecks(row)}
                                        tooltip={`Named in ${row.mentioned} of ${pluralize(answeredChecks(row), 'answer')}`}
                                    />
                                </span>
                            </li>
                        ))}
                    </ul>
                </div>
            </div>
        </div>
    )
}
