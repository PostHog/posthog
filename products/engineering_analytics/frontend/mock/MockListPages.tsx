/** Full list pages — the unvalued lens. "pr: any" / "author: any" resolve here; picking a row
 *  values the filter and focuses the same view on one entity. Faked data throughout. */

import { LemonCard } from '@posthog/lemon-ui'

import { MOCK_AUTHORS, MOCK_PRS } from './mockData'
import { DeltaBadge, MockEntityHeader, MockHeaderBar, MockPrTable, Section, ShareRow, fmtUsd } from './shared'

export function MockPrListPage(): JSX.Element {
    return (
        <div>
            <MockHeaderBar branch="all branches" lensFilter={{ label: 'pr: any', clearTo: { page: 'repo' } }} />
            <MockEntityHeader
                title="Pull requests"
                slug={<>the unvalued pr lens — pick a row to focus the same view on one PR</>}
                right={undefined}
            />
            <Section
                id="pr-list"
                title="All pull requests"
                note="server-paginated and filterable in the real build — 988 open, 57.5k total"
            >
                <LemonCard hoverEffect={false} className="p-0">
                    <MockPrTable prs={MOCK_PRS} />
                    <div className="border-t border-primary px-4 py-2 text-[11px] text-tertiary">
                        Showing {MOCK_PRS.length} of 988 open · search, state, CI, author, and label filters live here.
                    </div>
                </LemonCard>
            </Section>
        </div>
    )
}

export function MockAuthorListPage(): JSX.Element {
    return (
        <div>
            <MockHeaderBar branch="all branches" lensFilter={{ label: 'author: any', clearTo: { page: 'repo' } }} />
            <MockEntityHeader
                title="Authors"
                slug={<>the unvalued author lens — pick a row to focus the same view on one author</>}
                right={undefined}
            />
            <Section
                id="author-list"
                title="All authors"
                note="184 distinct authors in the last 30 days — sortable, not a ranking"
            >
                <LemonCard hoverEffect={false} className="p-4">
                    {MOCK_AUTHORS.map((a) => (
                        <ShareRow
                            key={a.handle}
                            avatar={a.handle}
                            label={a.handle}
                            sub={`median open→merge ${a.medianMergeHours}h · ${a.rerunCycles} re-run cycles`}
                            value={`${a.prs30d} PRs`}
                            valueSub={
                                <>
                                    {fmtUsd(a.ciCost30d)} CI cost · <DeltaBadge value={a.prsDelta} unit="" />
                                </>
                            }
                            to={{ page: 'author', handle: a.handle }}
                        />
                    ))}
                    <div className="mt-2 border-t border-primary pt-2 text-[11px] text-tertiary">
                        Showing 5 of 184 authors active in the window — bots are a separate cohort.
                    </div>
                </LemonCard>
            </Section>
        </div>
    )
}
