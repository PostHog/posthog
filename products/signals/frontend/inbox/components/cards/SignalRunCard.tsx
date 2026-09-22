import clsx from 'clsx'

import { IconCompass, IconSignal } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { captureInboxRunOpened } from '../../inboxAnalytics'
import { SignalRun } from '../../types'
import { stripScoutPrefix } from '../../utils/scoutRunsWindow'
import { inboxCardRowClassName } from './inboxCardRowClassName'
import { resolveRunVariant, RunStatusIndicator } from './runStatusVariant'

export function SignalRunCard({ run }: { run: SignalRun }): JSX.Element {
    const isScout = run.kind === 'scout'
    const displayTitle = isScout ? stripScoutPrefix(run.title) : run.title

    return (
        <div className={clsx('relative', inboxCardRowClassName(false))}>
            <Link
                to={urls.taskDetail(run.task_id)}
                onClick={() =>
                    captureInboxRunOpened({ kind: run.kind, status: run.status, hasReport: !!run.report_id })
                }
                className="flex min-w-0 flex-1 items-start gap-2.5 text-left text-inherit no-underline"
            >
                <div className="flex flex-col gap-1 min-w-0 flex-1">
                    <span
                        className={clsx(
                            'min-w-0 truncate text-sm leading-snug',
                            isScout ? 'font-mono' : 'font-semibold'
                        )}
                    >
                        {displayTitle || 'Untitled run'}
                    </span>
                    <div className="flex items-center flex-wrap gap-x-2 gap-y-0.5 text-xs text-tertiary leading-none select-none">
                        <LemonTag
                            icon={
                                isScout ? (
                                    <IconCompass className="text-tertiary" />
                                ) : (
                                    <IconSignal className="text-tertiary" />
                                )
                            }
                        >
                            {isScout ? 'Scout' : 'Signal'}
                        </LemonTag>
                        <RunStatusIndicator variant={resolveRunVariant(run.status)} />
                        <span aria-hidden>·</span>
                        <span>
                            Started <TZLabel time={run.created_at} className="tabular-nums align-baseline" />
                        </span>
                    </div>
                </div>
            </Link>

            {run.report_id && (
                <div className="flex items-center shrink-0 @lg:self-stretch @lg:border-l @lg:border-primary @lg:pl-3">
                    <Link
                        to={urls.inboxReport('reports', run.report_id)}
                        className="text-xs font-medium text-accent no-underline"
                    >
                        View report
                    </Link>
                </div>
            )}
        </div>
    )
}
