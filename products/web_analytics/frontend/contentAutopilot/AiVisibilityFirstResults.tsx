import { useActions, useValues } from 'kea'

import { Heading, Skeleton, Text } from '@posthog/quill'

import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { aiVisibilityFirstResultsLogic } from './aiVisibilityFirstResultsLogic'
import { AiVisibilityTable } from './AiVisibilityTable'
import { AiVisibilityTag } from './AiVisibilityTag'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { ContentAutopilotKpiStat } from './ContentAutopilotKpiStat'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import { ContentAutopilotStatStrip } from './ContentAutopilotStatStrip'
import { ShareOfVoiceRow, answeredChecks, firstResultsView } from './firstResults'
import { sortEngines } from './utils'

const share = (part: number, whole: number): string => (whole > 0 ? percentage(part / whole, 0) : '-')

const FIRST_RESULT_LABELS = {
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
} as const

export const AiVisibilityFirstResults = (): JSX.Element => {
    const { firstResults, firstResultsLoading } = useValues(aiVisibilityFirstResultsLogic)
    const { loadFirstResults } = useActions(aiVisibilityFirstResultsLogic)

    if (!firstResults) {
        return firstResultsLoading ? (
            <Skeleton className="h-96 w-full" />
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
            <Heading size="sm" render={<h3 className="m-0" />}>
                How AI answers see {brandName}
            </Heading>
            <Text size="sm" variant="muted" render={<p className="m-0 mt-1" />}>
                Here is your current overview. We'll keep tracking your brand, so you'll see trends here soon.
            </Text>

            <ContentAutopilotStatStrip
                className="mt-4 grid-cols-1 sm:grid-cols-3"
                data-attr="ai-visibility-first-results-kpis"
            >
                <ContentAutopilotKpiStat {...FIRST_RESULT_LABELS.named} value={share(view.named, view.openAnswers)} />
                <ContentAutopilotKpiStat {...FIRST_RESULT_LABELS.cited} value={share(view.cited, view.openAnswers)} />
                <ContentAutopilotKpiStat
                    {...FIRST_RESULT_LABELS.branded}
                    value={share(view.brandedCited, view.brandedAnswers)}
                    note={view.brandedAnswers > 0 ? undefined : 'No prompts name your brand'}
                />
            </ContentAutopilotStatStrip>

            <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
                <div className="min-w-0 lg:col-span-2">
                    <Heading size="sm" render={<h4 className="m-0" />}>
                        Top brands mentioned
                    </Heading>
                    <Text size="xs" variant="muted" render={<p className="m-0 mt-1 mb-2" />}>
                        Brands named in at least one of the {pluralize(view.openAnswers, 'answer')}, and you.{' '}
                        {rankings.competitors_confirmed
                            ? 'They are the competitors you confirmed.'
                            : 'They are the competitors PostHog suggested. Choose yours below.'}
                    </Text>
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
                                            <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                                {row.domain}
                                            </Text>
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
                    <Heading size="sm" render={<h4 className="m-0" />}>
                        By engine
                    </Heading>
                    <Text size="xs" variant="muted" render={<p className="m-0 mt-1 mb-2" />}>
                        Answers that named you, per engine.
                    </Text>
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
                                        tooltip={`Out of ${pluralize(answeredChecks(row), 'answer')}`}
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
