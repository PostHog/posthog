import clsx from 'clsx'

import { Tooltip } from '@posthog/lemon-ui'

import { positionLabel } from './promptReport'

const Result = ({ dotClassName, children }: { dotClassName: string; children: React.ReactNode }): JSX.Element => (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
        <span className={clsx('size-1.5 shrink-0 rounded-full', dotClassName)} aria-hidden />
        <span>{children}</span>
    </span>
)

export const ContentAutopilotCheckResult = ({
    cited,
    checkFailed,
    position,
}: {
    cited: boolean
    checkFailed: boolean
    position?: number | null
}): JSX.Element =>
    checkFailed ? (
        <Result dotClassName="bg-danger">Failed</Result>
    ) : cited ? (
        <Tooltip title={position ? `Your site is source ${position} in this answer` : undefined}>
            <span>
                <Result dotClassName="bg-success">{position ? `Cited ${positionLabel(position)}` : 'Cited'}</Result>
            </span>
        </Tooltip>
    ) : (
        <Result dotClassName="bg-[var(--color-text-tertiary)]">
            <span className="text-secondary">Not cited</span>
        </Result>
    )
