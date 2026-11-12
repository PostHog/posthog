import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { urls } from 'scenes/urls'

export type StamphogTabKey = 'repositories' | 'runs' | 'team' | 'digests'

// Top-level tab strip for stamphog. Every tab is team-scoped, so this is purely presentational —
// each scene passes the key it is. Repositories stays first: it's the only tab you have to visit
// before the other tabs have anything to show.
export function StamphogTabs({ activeKey }: { activeKey: StamphogTabKey }): JSX.Element {
    return (
        <LemonTabs
            activeKey={activeKey}
            sceneInset
            tabs={[
                {
                    key: 'repositories' satisfies StamphogTabKey,
                    label: 'Repositories',
                    link: urls.stamphog(),
                },
                {
                    key: 'runs' satisfies StamphogTabKey,
                    label: 'Runs',
                    link: urls.stamphogRuns(),
                },
                {
                    key: 'team' satisfies StamphogTabKey,
                    label: 'Team view',
                    link: urls.stamphogTeamView(),
                },
                {
                    key: 'digests' satisfies StamphogTabKey,
                    label: 'Digests',
                    link: urls.stamphogDigests(),
                },
            ]}
        />
    )
}
