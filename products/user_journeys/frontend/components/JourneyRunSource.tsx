import { IconGitBranch } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import type { JourneyRunApi } from '../generated/api.schemas'
import { RUN_TRIGGER_LABELS, shortCommitSha } from '../journeyRuns'

/** What started a run, with the commit and branch a deploy sent. */
export function JourneyRunSource({
    run,
}: {
    run: Pick<JourneyRunApi, 'trigger' | 'commit_sha' | 'branch'>
}): JSX.Element {
    return (
        <div className="flex items-center gap-x-2 gap-y-1 flex-wrap min-w-0">
            <LemonTag type={run.trigger === 'deploy' ? 'highlight' : 'default'}>
                {RUN_TRIGGER_LABELS[run.trigger]}
            </LemonTag>
            {run.commit_sha ? (
                <span className="font-mono text-xs" title={run.commit_sha} translate="no">
                    {shortCommitSha(run.commit_sha)}
                </span>
            ) : null}
            {run.branch ? (
                <span className="flex items-center gap-1 text-xs text-secondary min-w-0" title={run.branch}>
                    <IconGitBranch className="shrink-0" />
                    <span className="font-mono truncate" translate="no">
                        {run.branch}
                    </span>
                </span>
            ) : null}
        </div>
    )
}
