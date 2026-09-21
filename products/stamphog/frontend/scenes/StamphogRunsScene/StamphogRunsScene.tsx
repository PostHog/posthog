import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { StamphogTabs } from '../../components/StamphogTabs'
import { ReviewRunApi } from '../../generated/api.schemas'
import { ExpandedRunDetails } from './ExpandedRunDetails'
import { TRIGGER_OPTIONS, runDuration, shortSha, statusDisplay, triggerLabel, verdictDisplay } from './runDisplay'
import { RUNS_PAGE_SIZE, stamphogRunsSceneLogic } from './stamphogRunsSceneLogic'

export const scene: SceneExport = {
    component: StamphogRunsScene,
    logic: stamphogRunsSceneLogic,
}

function RunFilters(): JSX.Element {
    const { repository, trigger, repositoryOptions, repoConfigsLoading } = useValues(stamphogRunsSceneLogic)
    const { setRepository, setTrigger } = useActions(stamphogRunsSceneLogic)

    return (
        <div className="flex gap-2 flex-wrap items-center">
            <LemonSelect
                value={repository}
                onChange={setRepository}
                loading={repoConfigsLoading}
                placeholder="All repositories"
                className="min-w-60"
                options={[{ value: null, label: 'All repositories' }, ...repositoryOptions]}
                data-attr="stamphog-runs-repository-filter"
            />
            <LemonSelect
                value={trigger}
                onChange={setTrigger}
                placeholder="Any trigger"
                className="min-w-40"
                options={[{ value: null, label: 'Any trigger' }, ...TRIGGER_OPTIONS]}
                data-attr="stamphog-runs-trigger-filter"
            />
        </div>
    )
}

function RunsTable(): JSX.Element {
    const { runs, runCount, runsResponseLoading, runsFailed, page } = useValues(stamphogRunsSceneLogic)
    const { setPage, loadRuns } = useActions(stamphogRunsSceneLogic)

    const columns: LemonTableColumns<ReviewRunApi> = [
        {
            title: 'Started',
            dataIndex: 'created_at',
            render: (created_at) => <TZLabel time={created_at as string} />,
        },
        {
            title: 'Repository',
            dataIndex: 'repository',
            render: (repository) => <span className="font-mono text-xs">{repository as string}</span>,
        },
        {
            title: 'Pull request',
            key: 'pull_request',
            render: (_, run) => (
                <div className="flex items-center gap-2 min-w-0">
                    <Link to={run.pr_url} target="_blank" className="font-mono text-xs shrink-0">
                        #{run.pr_number}
                    </Link>
                    <span className="truncate">{run.title}</span>
                </div>
            ),
        },
        {
            title: 'Author',
            dataIndex: 'author_login',
            render: (author_login) => <span className="font-mono text-xs">{author_login as string}</span>,
        },
        {
            title: 'Trigger',
            key: 'trigger',
            render: (_, run) => <LemonTag type="option">{triggerLabel(run.trigger)}</LemonTag>,
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, run) => {
                const { type, label } = statusDisplay(run.status)
                return <LemonTag type={type}>{label}</LemonTag>
            },
        },
        {
            title: 'Verdict',
            key: 'verdict',
            render: (_, run) => {
                const { type, label } = verdictDisplay(run.verdict)
                return <LemonTag type={type}>{label}</LemonTag>
            },
        },
        {
            title: 'Head',
            dataIndex: 'head_sha',
            render: (head_sha) => <span className="font-mono text-xs">{shortSha(head_sha as string)}</span>,
        },
        {
            title: 'Took',
            key: 'duration',
            render: (_, run) => <span className="font-mono text-xs">{runDuration(run)}</span>,
        },
    ]

    if (runsFailed) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadRuns() }}
                data-attr="stamphog-runs-error"
            >
                Could not load runs. This is usually temporary.
            </LemonBanner>
        )
    }

    return (
        <LemonTable
            columns={columns}
            dataSource={runs}
            loading={runsResponseLoading}
            rowKey="id"
            expandable={{ expandedRowRender: (run) => <ExpandedRunDetails run={run} /> }}
            pagination={{
                controlled: true,
                pageSize: RUNS_PAGE_SIZE,
                currentPage: page,
                entryCount: runCount,
                onForward: () => setPage(page + 1),
                onBackward: () => setPage(page - 1),
            }}
            emptyState="No runs yet. Stamphog records one here every time it looks at a pull request."
        />
    )
}

export function StamphogRunsScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Runs"
                description="Every time Stamphog reviewed a pull request, and what it decided."
                resourceType={{ type: 'stamphog' }}
            />
            <StamphogTabs activeKey="runs" />
            <RunFilters />
            <RunsTable />
        </SceneContent>
    )
}

export default StamphogRunsScene
