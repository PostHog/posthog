import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCard, Spinner } from '@posthog/lemon-ui'

import { AREA_WINDOW_OPTIONS } from './areaDisplay'
import { AreaGroupTable } from './AreaGroupTable'
import { AREA_PAGE_SIZE, stamphogAreaSceneLogic } from './stamphogAreaSceneLogic'

function HeadlineNumber({ value, label }: { value: number; label: string }): JSX.Element {
    return (
        <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-semibold">{value}</span>
            <span className="text-secondary">{label}</span>
        </div>
    )
}

export function AreaList(): JSX.Element {
    const { owner, windowDays, groups, headline, runsResponse, runsResponseLoading, runsFailed, showsOnlyNewest } =
        useValues(stamphogAreaSceneLogic)
    const { loadRuns } = useActions(stamphogAreaSceneLogic)

    if (!owner) {
        return (
            <LemonBanner type="info" data-attr="stamphog-area-no-team">
                Pick your team to see the pull requests that changed code it owns.
            </LemonBanner>
        )
    }

    if (runsFailed) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadRuns() }}
                data-attr="stamphog-area-error"
            >
                Couldn't load pull requests. Try again, and if it keeps happening, contact support.
            </LemonBanner>
        )
    }

    if (runsResponseLoading || !runsResponse) {
        return (
            <div className="flex items-center gap-2 text-secondary p-4" data-attr="stamphog-area-loading">
                <Spinner />
                Loading pull requests
            </div>
        )
    }

    if (groups.length === 0) {
        const windowLabel = AREA_WINDOW_OPTIONS.find((option) => option.value === windowDays)?.label.toLowerCase()
        return (
            <LemonBanner type="info" data-attr="stamphog-area-empty">
                No pull requests changed {owner}'s code in the {windowLabel}.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <LemonCard hoverEffect={false} className="flex flex-wrap items-baseline gap-x-8 gap-y-2 py-3">
                <HeadlineNumber
                    value={headline.changed}
                    label={
                        headline.changed === 1 ? 'pull request changed your code' : 'pull requests changed your code'
                    }
                />
                <HeadlineNumber value={headline.mergedWithoutTeam} label="merged without your team" />
                <HeadlineNumber value={headline.sensitive} label="touched a sensitive path" />
                <span className="text-secondary text-xs ml-auto">
                    {showsOnlyNewest
                        ? `Showing the newest ${AREA_PAGE_SIZE}. Sorted by how much of your code changed`
                        : 'Sorted by how much of your code changed'}
                </span>
            </LemonCard>
            {groups.map((group) => (
                <section key={group.key} className="flex flex-col gap-1">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-secondary mb-0">{group.title}</h3>
                    <AreaGroupTable group={group.key} rows={group.rows} />
                </section>
            ))}
        </div>
    )
}
