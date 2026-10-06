import { useValues } from 'kea'

import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'

import { CIActivityCommit } from '../../lib/ciExplorerActivity'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'

/** One commit of the activity timeline. The whole row is a link to that commit's CI. */
export function CIExplorerActivityCommit({ commit }: { commit: CIActivityCommit }): JSX.Element {
    const { locationUrl } = useValues(ciExplorerLogic)
    return (
        <Link
            // The newest commit is the overview, so its link carries no commit.
            to={locationUrl({ view: 'overview', headSha: commit.latest ? null : commit.headSha, nodeId: null })}
            subtle
            className="my-1 flex flex-wrap items-center justify-between gap-x-6 gap-y-1 rounded border border-primary bg-surface-primary p-3 hover:bg-surface-secondary"
            data-attr="ci-explorer-activity-commit"
        >
            <span className="flex items-center gap-2 text-sm font-medium">
                {commit.mergeQueue ? 'Merge queue' : 'Commit'}
                <code className="font-mono text-xs">{commit.headSha.slice(0, 7)}</code>
                {commit.latest && (
                    <LemonTag type="muted" size="small">
                        Current commit
                    </LemonTag>
                )}
            </span>
            <span className="flex flex-wrap items-center gap-x-3 text-xs tabular-nums text-secondary">
                <span>{pluralize(commit.runs, 'workflow run')}</span>
                {commit.failed > 0 && (
                    <Tooltip title="Workflow runs that failed on this commit, re-runs included. It is not the commit's latest result.">
                        <span className="text-danger">{commit.failed} failed</span>
                    </Tooltip>
                )}
                {commit.elapsedSeconds !== null && (
                    <Tooltip title="First run start to last run update, with re-runs and idle gaps">
                        <span className="font-mono">
                            Elapsed {humanFriendlyDuration(commit.elapsedSeconds, { maxUnits: 2 })}
                        </span>
                    </Tooltip>
                )}
            </span>
        </Link>
    )
}
