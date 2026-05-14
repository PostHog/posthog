import { IconCheck, IconLock, IconSparkles } from '@posthog/icons'
import { LemonCard, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import {
    buildReferralInviteStages,
    REFERRAL_MILESTONE_COUNT,
    referralRewardStages,
    referralRewardsEarnedCount,
    referralRewardsTotalCount,
    type ReferralInviteStage,
} from './referralInviteMilestoneModel'

function questTileClassNames(stage: ReferralInviteStage): string {
    return cn(
        'flex min-h-[7rem] w-full cursor-default flex-col items-center gap-2 rounded-none border p-2.5 text-center outline-none transition-colors motion-safe:hover:bg-fill-secondary min-[400px]:min-h-[7.25rem]',
        stage.locked && 'border-dashed border-primary bg-fill-secondary opacity-90 grayscale-[0.15]',
        stage.complete && 'border-success bg-success-highlight',
        !stage.complete &&
            !stage.locked &&
            stage.isCurrent &&
            'border-accent bg-surface-primary ring-1 ring-inset ring-accent/40',
        !stage.complete && !stage.locked && !stage.isCurrent && 'border-primary bg-fill-secondary'
    )
}

function rewardTileClassNames(stage: ReferralInviteStage): string {
    return cn(
        'flex min-h-[7rem] w-full cursor-default flex-col items-center gap-2 rounded-none border-2 p-2.5 text-center outline-none transition-[transform,box-shadow] motion-safe:hover:-translate-y-px motion-safe:hover:shadow-md motion-safe:hover:shadow-accent/15 min-[400px]:min-h-[7.25rem]',
        stage.locked && 'border-dashed border-accent/55 bg-accent-highlight-secondary/40',
        stage.complete && 'border-success bg-success-highlight shadow-sm shadow-success/15',
        !stage.complete &&
            !stage.locked &&
            stage.isCurrent &&
            'border-warning bg-warning-highlight ring-2 ring-inset ring-warning/40',
        !stage.complete && !stage.locked && !stage.isCurrent && 'border-accent/45 bg-warning-highlight/35'
    )
}

function questIconWrapClassNames(stage: ReferralInviteStage): string {
    return cn(
        'flex size-10 shrink-0 items-center justify-center rounded-full transition-colors duration-200',
        stage.complete && 'bg-success-highlight text-success border border-success/35',
        !stage.complete &&
            stage.isCurrent &&
            'bg-accent text-white motion-safe:[animation:referral-current-nudge_3s_ease-in-out_infinite]',
        !stage.complete &&
            !stage.isCurrent &&
            !stage.locked &&
            'bg-accent-highlight-secondary text-accent border border-accent/25',
        !stage.complete && stage.locked && 'bg-fill-tertiary text-secondary border border-primary'
    )
}

function rewardIconWrapClassNames(stage: ReferralInviteStage): string {
    return cn(
        'flex size-10 shrink-0 items-center justify-center rounded-full transition-colors duration-200',
        stage.complete && 'bg-success-highlight text-success border-2 border-success/40',
        !stage.complete &&
            stage.isCurrent &&
            'border-2 border-accent/35 bg-accent text-white shadow-md motion-safe:[animation:referral-current-nudge_3s_ease-in-out_infinite]',
        !stage.complete &&
            !stage.isCurrent &&
            !stage.locked &&
            'border border-warning/50 bg-warning-highlight text-warning-dark',
        !stage.complete && stage.locked && 'border border-accent/40 bg-accent-highlight-secondary text-accent'
    )
}

function QuestOrRewardTiles({
    stages,
    variant,
}: {
    stages: ReferralInviteStage[]
    variant: 'quest' | 'reward'
}): JSX.Element {
    const rowStages = variant === 'reward' ? referralRewardStages(stages) : stages

    return (
        <div
            className={cn(
                'grid w-full items-stretch gap-2',
                variant === 'reward' ? 'grid-cols-1 min-[320px]:grid-cols-3' : 'grid-cols-2 min-[400px]:grid-cols-4'
            )}
        >
            {rowStages.map((stage, index) => {
                const tooltipTitle =
                    variant === 'quest'
                        ? stage.reward
                            ? `${stage.hint} Reward: ${stage.reward}`
                            : stage.hint
                        : `${stage.reward} — unlocked when: ${stage.label}.`

                return (
                    <div
                        key={`${variant}-${stage.label}-${stage.reward ?? ''}-${index}`}
                        className="flex min-h-0 h-full"
                    >
                        <Tooltip title={tooltipTitle} placement="top" delayMs={200}>
                            <div
                                className={
                                    variant === 'quest' ? questTileClassNames(stage) : rewardTileClassNames(stage)
                                }
                            >
                                <div
                                    className={
                                        variant === 'quest'
                                            ? questIconWrapClassNames(stage)
                                            : rewardIconWrapClassNames(stage)
                                    }
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
                                <div
                                    className={cn(
                                        'flex w-full flex-1 flex-col items-center justify-center px-0.5',
                                        variant === 'quest' ? 'min-h-[2.75rem] gap-1' : 'py-0.5'
                                    )}
                                >
                                    {variant === 'quest' ? (
                                        <span className="line-clamp-2 w-full text-xs font-medium leading-snug text-default">
                                            {stage.label}
                                        </span>
                                    ) : (
                                        <span
                                            className="line-clamp-3 w-full text-xs font-semibold leading-snug text-accent"
                                            data-attr="referral-milestone-reward"
                                        >
                                            {stage.reward}
                                        </span>
                                    )}
                                </div>
                            </div>
                        </Tooltip>
                    </div>
                )
            })}
        </div>
    )
}

export function ReferralInviteMilestoneProgress({
    firstEventSent,
    layout = 'default',
}: {
    firstEventSent: boolean
    /** Inside referral rows: one bordered panel with columns instead of two LemonCards */
    layout?: 'default' | 'embedded'
}): JSX.Element {
    const { stages, completedCount: completed } = buildReferralInviteStages(firstEventSent)
    const questPct = (completed / REFERRAL_MILESTONE_COUNT) * 100
    const questPctRounded = Math.round(questPct)
    const isQuestMaxed = completed >= REFERRAL_MILESTONE_COUNT

    const rewardsEarned = referralRewardsEarnedCount(stages)
    const rewardsTotal = referralRewardsTotalCount(stages)
    const rewardsPct = rewardsTotal > 0 ? (rewardsEarned / rewardsTotal) * 100 : rewardsEarned > 0 ? 100 : 0
    const rewardsPctRounded = Math.round(rewardsPct)
    const isRewardsMaxed = rewardsTotal > 0 && rewardsEarned >= rewardsTotal

    const embedded = layout === 'embedded'

    const questHeaderBlock = (
        <div className={cn('space-y-1 border-b border-primary pb-2', embedded ? 'pt-0' : 'relative px-4 pt-3 pb-2')}>
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                    <p className="m-0 flex items-center gap-2.5 text-lg font-semibold text-default tracking-tight">
                        <span className="inline-flex items-center justify-center rounded-none border border-accent bg-accent-highlight-secondary p-1.5">
                            <IconSparkles className="size-5 text-accent motion-safe:animate-pulse" />
                        </span>
                        Quest progress
                    </p>
                    <p className="m-0 text-secondary text-[15px] font-normal leading-snug">
                        Rack up milestones as they ship. More drops incoming.
                    </p>
                </div>
                <LemonTag type={isQuestMaxed ? 'success' : 'highlight'} size="small">
                    Lv.{completed}
                    <span className="mx-0.5 opacity-80">/</span>
                    {REFERRAL_MILESTONE_COUNT}
                </LemonTag>
            </div>
        </div>
    )

    const questProgressAndTiles = (
        <div className={cn('relative flex flex-col gap-2', embedded ? 'px-0 pb-0 pt-2' : 'px-3 pb-4 pt-2')}>
            <div className="rounded-none border border-primary bg-fill-secondary p-3">
                <div className="mb-2 flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-secondary">Milestones</span>
                    <span className="text-sm font-medium text-default tabular-nums">{questPctRounded}%</span>
                </div>
                <div
                    className="h-1.5 w-full overflow-hidden rounded-none bg-fill-tertiary"
                    role="progressbar"
                    aria-valuenow={questPctRounded}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label="Referral quest milestone progress"
                >
                    <div
                        className={cn(
                            'h-full rounded-none transition-[width] duration-150 ease-out',
                            isQuestMaxed ? 'bg-success' : 'bg-accent'
                        )}
                        style={{ width: `${questPct}%` }}
                    />
                </div>
            </div>

            <QuestOrRewardTiles stages={stages} variant="quest" />
        </div>
    )

    const rewardsHeaderBlock = (
        <div
            className={cn(
                'space-y-1 border-b border-accent/30 bg-warning-highlight/25 pb-2',
                embedded ? 'px-0 pt-0' : 'px-4 pt-3 pb-2'
            )}
        >
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                    <p className="m-0 flex items-center gap-2.5 text-lg font-semibold text-default tracking-tight">
                        <span className="inline-flex items-center justify-center rounded-none border-2 border-accent/30 bg-accent p-2">
                            <IconSparkles className="size-5 text-white" />
                        </span>
                        Swag stash
                    </p>
                    <p className="m-0 text-secondary text-[15px] font-normal leading-snug">
                        Coupons, merch drops, and surprises — unlocked as milestones land.
                    </p>
                </div>
                <LemonTag type={isRewardsMaxed ? 'success' : 'warning'} size="small">
                    {rewardsEarned}
                    <span className="mx-0.5 opacity-80">/</span>
                    {rewardsTotal}
                    <span className="ml-1 opacity-80">unlocked</span>
                </LemonTag>
            </div>
        </div>
    )

    const rewardsProgressAndTiles = (
        <div className={cn('flex flex-col gap-2', embedded ? 'px-0 pb-0 pt-2' : 'px-3 pb-4 pt-2')}>
            <div className="rounded-none border-2 border-accent/35 bg-warning-highlight/30 p-3">
                <div className="mb-2 flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold text-accent">Loot meter</span>
                    <span className="text-sm font-bold tabular-nums text-default">{rewardsPctRounded}%</span>
                </div>
                <div
                    className="h-2 w-full overflow-hidden rounded-none border border-accent/20 bg-accent-highlight-secondary/80"
                    role="progressbar"
                    aria-valuenow={rewardsPctRounded}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label="Referral rewards unlock progress"
                >
                    <div
                        className={cn(
                            'h-full rounded-none transition-[width] duration-150 ease-out',
                            isRewardsMaxed ? 'bg-success' : 'bg-accent'
                        )}
                        style={{ width: `${rewardsPct}%` }}
                    />
                </div>
            </div>

            <QuestOrRewardTiles stages={stages} variant="reward" />
        </div>
    )

    return (
        <>
            <style>{`
                    @keyframes referral-current-nudge {
                        0%, 100% { transform: rotate(-0.5deg) scale(1); }
                        50% { transform: rotate(0.5deg) scale(1.01); }
                    }
                `}</style>
            {embedded ? (
                <div
                    className="flex w-full flex-col divide-y divide-primary overflow-hidden rounded-none border border-primary bg-surface-primary sm:flex-row sm:divide-x sm:divide-y-0"
                    data-attr="referral-invite-milestones-embedded"
                >
                    <div
                        className="flex min-w-0 flex-1 flex-col gap-2 p-3 sm:p-4"
                        data-attr="referral-invite-milestones-quest"
                    >
                        {questHeaderBlock}
                        {questProgressAndTiles}
                    </div>
                    <div
                        className="flex min-w-0 flex-1 flex-col gap-2 p-3 sm:p-4"
                        data-attr="referral-invite-milestones-rewards"
                    >
                        {rewardsHeaderBlock}
                        {rewardsProgressAndTiles}
                    </div>
                </div>
            ) : (
                <div className="mx-auto flex w-full max-w-6xl flex-row items-stretch gap-3 px-4 py-2">
                    <LemonCard
                        hoverEffect={false}
                        className="relative min-w-0 flex-1 gap-0 overflow-hidden rounded-2xl border-2 border-primary p-0 shadow-sm"
                        data-attr="referral-invite-milestones-quest"
                    >
                        {questHeaderBlock}
                        {questProgressAndTiles}
                    </LemonCard>

                    <LemonCard
                        hoverEffect={false}
                        className="relative min-w-0 flex-1 gap-0 overflow-hidden rounded-3xl border-[3px] border-accent p-0 shadow-lg shadow-accent/20"
                        data-attr="referral-invite-milestones-rewards"
                    >
                        <div className="flex flex-col">
                            {rewardsHeaderBlock}
                            {rewardsProgressAndTiles}
                        </div>
                    </LemonCard>
                </div>
            )}
        </>
    )
}
