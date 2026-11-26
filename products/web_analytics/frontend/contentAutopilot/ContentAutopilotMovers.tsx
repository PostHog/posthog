import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import { contentAutopilotMoversLogic } from './contentAutopilotMoversLogic'
import { ContentAutopilotPageMoversTable } from './ContentAutopilotPageMoversTable'
import { ContentAutopilotPromptMoversTable } from './ContentAutopilotPromptMoversTable'
import { ContentAutopilotTileSkeleton } from './ContentAutopilotTileSkeleton'

const PROMPTS_TITLE = 'Prompts that moved most'
const PAGES_TITLE = 'Your pages that moved most'
const GRID_CLASS_NAME = 'grid grid-cols-1 @3xl/prompts-overview:grid-cols-2 gap-4'

/** The prompts and the pages on your site that gained and lost the most against the window before. It sits in the
 *  overview, whose container its columns break on. */
export const ContentAutopilotMovers = (): JSX.Element | null => {
    const { movers, moversLoading, moversError } = useValues(contentAutopilotMoversLogic)
    const { loadMovers, openMoverPrompt } = useActions(contentAutopilotMoversLogic)

    // The overview shows the notice for a project without access, so the tile adds nothing.
    if (moversError === 'forbidden') {
        return null
    }
    if (moversError === 'failed') {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: loadMovers, loading: moversLoading }}
                data-attr="content-autopilot-movers-error"
            >
                Couldn't load the prompts and pages that moved most. Try again, and if it keeps happening contact
                support.
            </LemonBanner>
        )
    }
    if (!movers) {
        return (
            <div className={GRID_CLASS_NAME}>
                <ContentAutopilotTileSkeleton title={PROMPTS_TITLE} />
                <ContentAutopilotTileSkeleton title={PAGES_TITLE} />
            </div>
        )
    }

    const { days, min_answers: minAnswers } = movers
    const before = `the ${days} days before`
    const promptsMoved = movers.prompt_gainers.length + movers.prompt_losers.length > 0
    const pagesMoved = movers.page_gainers.length + movers.page_losers.length > 0
    const pagesComparable = Math.min(movers.answers, movers.previous_answers) >= minAnswers
    return (
        <div
            className={clsx(
                GRID_CLASS_NAME,
                'transition-opacity motion-reduce:transition-none',
                // The rows on screen belong to the previous filters until the new ones arrive.
                moversLoading && 'opacity-50'
            )}
            aria-busy={moversLoading}
            data-attr="content-autopilot-movers"
        >
            <PagePerformanceCard className="min-w-0">
                <PagePerformanceCardHeader
                    title={PROMPTS_TITLE}
                    description={`A prompt needs at least ${minAnswers} answers in both periods to be compared.`}
                />
                {promptsMoved ? (
                    <div className="overflow-x-auto" data-attr="content-autopilot-movers-prompts">
                        <ContentAutopilotPromptMoversTable
                            rows={[...movers.prompt_gainers, ...movers.prompt_losers]}
                            days={days}
                            onOpenPrompt={({ prompt_id, change }) =>
                                openMoverPrompt(prompt_id, change > 0 ? 'gained' : 'lost')
                            }
                        />
                    </div>
                ) : (
                    <p className="m-0 p-3 text-secondary" data-attr="content-autopilot-movers-prompts-empty">
                        No prompt changed against {before}. A prompt is compared once it has at least {minAnswers}{' '}
                        answers in each period.
                    </p>
                )}
            </PagePerformanceCard>
            <PagePerformanceCard className="min-w-0">
                <PagePerformanceCardHeader title={PAGES_TITLE} />
                {pagesMoved ? (
                    <div className="overflow-x-auto" data-attr="content-autopilot-movers-pages">
                        <ContentAutopilotPageMoversTable
                            rows={[...movers.page_gainers, ...movers.page_losers]}
                            days={days}
                            dateFrom={movers.window_from}
                            dateTo={movers.window_to}
                            branded={movers.branded}
                        />
                    </div>
                ) : (
                    <p className="m-0 p-3 text-secondary" data-attr="content-autopilot-movers-pages-empty">
                        {pagesComparable
                            ? `No page on your site is cited more or less often than in ${before}.`
                            : `Pages are compared once there are at least ${minAnswers} answers in each period.`}
                    </p>
                )}
            </PagePerformanceCard>
        </div>
    )
}
