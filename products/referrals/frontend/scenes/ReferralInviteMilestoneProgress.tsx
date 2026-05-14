import { IconCheck, IconLock, IconSparkles } from '@posthog/icons'
import { LemonCard, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { buildReferralInviteStages, REFERRAL_MILESTONE_COUNT } from './referralInviteMilestoneModel'

export function ReferralInviteMilestoneProgress({ firstEventSent }: { firstEventSent: boolean }): JSX.Element {
    const { stages, completedCount: completed } = buildReferralInviteStages(firstEventSent)
    const pct = (completed / REFERRAL_MILESTONE_COUNT) * 100
    const isMaxed = completed >= REFERRAL_MILESTONE_COUNT
    const pctRounded = Math.round(pct)

    return (
        <>
            <style>{`
                    @keyframes referral-current-nudge {
                        0%, 100% { transform: rotate(-0.5deg) scale(1); }
                        50% { transform: rotate(0.5deg) scale(1.01); }
                    }
                `}</style>
            <LemonCard
                hoverEffect={false}
                className="relative ml-6 mr-2 my-2 max-w-lg gap-0 overflow-hidden rounded-2xl border-2 border-primary p-0 shadow-sm"
                data-attr="referral-invite-milestones"
            >
                <div className="relative space-y-1 border-b border-primary px-4 pt-3 pb-2">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 space-y-1">
                            <p className="m-0 flex items-center gap-2.5 text-lg font-semibold text-default tracking-tight">
                                <span className="inline-flex items-center justify-center rounded-lg border border-accent bg-accent-highlight-secondary p-1.5">
                                    <IconSparkles className="size-5 text-accent motion-safe:animate-pulse" />
                                </span>
                                Referral quest
                            </p>
                            <p className="m-0 text-secondary text-[15px] font-normal leading-snug">
                                Rack up milestones as they ship. More drops incoming.
                            </p>
                        </div>
                        <LemonTag type={isMaxed ? 'success' : 'highlight'} size="small">
                            Lv.{completed}
                            <span className="mx-0.5 opacity-80">/</span>
                            {REFERRAL_MILESTONE_COUNT}
                        </LemonTag>
                    </div>
                </div>
                <div className="relative flex flex-col gap-2 px-3 pb-4 pt-2">
                    <div className="rounded-lg border border-primary bg-fill-secondary p-3">
                        <div className="mb-2 flex items-center justify-between gap-3">
                            <span className="text-sm font-medium text-secondary">Progress</span>
                            <span className="text-sm font-medium text-default tabular-nums">{pctRounded}%</span>
                        </div>
                        <div
                            className="h-1.5 w-full overflow-hidden rounded-full bg-fill-tertiary"
                            role="progressbar"
                            aria-valuenow={pctRounded}
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-label="Referral milestone progress"
                        >
                            <div
                                className={cn(
                                    'h-full rounded-full transition-[width] duration-150 ease-out',
                                    isMaxed ? 'bg-success' : 'bg-accent'
                                )}
                                style={{ width: `${pct}%` }}
                            />
                        </div>
                    </div>

                    <div className="grid w-full grid-cols-2 items-stretch gap-2 min-[400px]:grid-cols-4">
                        {stages.map((stage, index) => (
                            <div key={index} className="flex min-h-0 h-full">
                                <Tooltip title={stage.hint} placement="top" delayMs={200}>
                                    <div
                                        className={cn(
                                            'flex min-h-[6.25rem] w-full cursor-default flex-col items-center gap-2 rounded-lg border p-2.5 text-center outline-none transition-colors motion-safe:hover:bg-fill-secondary min-[400px]:min-h-[6.5rem]',
                                            stage.locked &&
                                                'border-dashed border-primary bg-fill-secondary opacity-90 grayscale-[0.15]',
                                            stage.complete && 'border-success bg-success-highlight',
                                            !stage.complete &&
                                                !stage.locked &&
                                                stage.isCurrent &&
                                                'border-accent bg-surface-primary ring-1 ring-inset ring-accent/40',
                                            !stage.complete &&
                                                !stage.locked &&
                                                !stage.isCurrent &&
                                                'border-primary bg-fill-secondary'
                                        )}
                                    >
                                        <div
                                            className={cn(
                                                'flex size-10 shrink-0 items-center justify-center rounded-full transition-colors duration-200',
                                                stage.complete &&
                                                    'bg-success-highlight text-success border border-success/35',
                                                !stage.complete &&
                                                    stage.isCurrent &&
                                                    'bg-accent text-white motion-safe:[animation:referral-current-nudge_3s_ease-in-out_infinite]',
                                                !stage.complete &&
                                                    !stage.isCurrent &&
                                                    !stage.locked &&
                                                    'bg-accent-highlight-secondary text-accent border border-accent/25',
                                                !stage.complete &&
                                                    stage.locked &&
                                                    'bg-fill-tertiary text-secondary border border-primary'
                                            )}
                                        >
                                            {stage.complete ? (
                                                <IconCheck className="size-[22px] shrink-0 stroke-[2.5]" />
                                            ) : stage.locked ? (
                                                <IconLock className="size-[22px] shrink-0 opacity-95" />
                                            ) : stage.isCurrent ? (
                                                <IconSparkles className="size-[22px] shrink-0" />
                                            ) : (
                                                <span className="text-sm font-semibold tabular-nums leading-none text-default">
                                                    {index + 1}
                                                </span>
                                            )}
                                        </div>
                                        <div className="flex w-full min-h-[2.75rem] flex-1 flex-col items-center justify-center px-0.5">
                                            <span className="line-clamp-2 w-full text-xs font-medium leading-snug text-default">
                                                {stage.label}
                                            </span>
                                        </div>
                                    </div>
                                </Tooltip>
                            </div>
                        ))}
                    </div>
                </div>
            </LemonCard>
        </>
    )
}
