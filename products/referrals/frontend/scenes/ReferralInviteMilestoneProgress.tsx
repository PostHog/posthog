import { IconCheck, IconLock, IconSparkles } from '@posthog/icons'

import {
    Badge,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    cn,
    Progress,
    ProgressLabel,
    ProgressValue,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from 'lib/ui/quill'

import { buildReferralInviteStages, REFERRAL_MILESTONE_COUNT } from './referralInviteMilestoneModel'

export function ReferralInviteMilestoneProgress({ firstEventSent }: { firstEventSent: boolean }): JSX.Element {
    const { stages, completedCount: completed } = buildReferralInviteStages(firstEventSent)
    const pct = (completed / REFERRAL_MILESTONE_COUNT) * 100
    const progressVariant = completed >= REFERRAL_MILESTONE_COUNT ? 'success' : 'default'
    const isMaxed = completed >= REFERRAL_MILESTONE_COUNT

    return (
        <TooltipProvider delay={200}>
            <>
                <style>{`
                    @keyframes referral-current-nudge {
                        0%, 100% { transform: rotate(-0.5deg) scale(1); }
                        50% { transform: rotate(0.5deg) scale(1.01); }
                    }
                `}</style>
                <Card
                    className="relative ml-6 mr-2 my-2 max-w-lg gap-0 overflow-hidden rounded-2xl border-2 border-foreground/15 bg-card p-0 shadow-none"
                    data-attr="referral-invite-milestones"
                >
                    <CardHeader className="relative space-y-1 border-b-2 border-dashed border-foreground/10 px-4 pt-3 !pb-2">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0 space-y-1">
                                <CardTitle className="flex items-center gap-2.5 font-black text-lg leading-none tracking-tight">
                                    <span className="inline-flex items-center justify-center rounded-lg border-2 border-primary/50 bg-primary/20 p-1.5">
                                        <IconSparkles className="size-5 text-primary motion-safe:animate-pulse" />
                                    </span>
                                    Referral quest
                                </CardTitle>
                                <CardDescription className="text-[13px] font-semibold leading-snug text-muted-foreground">
                                    Rack up milestones as they ship. More drops incoming.
                                </CardDescription>
                            </div>
                            <Badge
                                variant={isMaxed ? 'success' : 'default'}
                                className={cn(
                                    'h-auto min-h-0 border-2 px-2.5 py-1 text-xs tabular-nums font-black leading-snug ring-0',
                                    isMaxed ? 'border-foreground/15' : 'border-primary/50 bg-primary/20 text-primary'
                                )}
                            >
                                Lv.{completed}
                                <span className="mx-0.5 font-normal opacity-80">/</span>
                                {REFERRAL_MILESTONE_COUNT}
                            </Badge>
                        </div>
                    </CardHeader>
                    <CardContent className="relative flex flex-col gap-2 px-3 pb-4 pt-2">
                        <div className="rounded-lg border-2 border-foreground/15 bg-muted/25 p-2">
                            <Progress value={pct} variant={progressVariant} className="w-full">
                                <ProgressLabel className="text-[10px] font-black tracking-[0.18em] text-muted-foreground">
                                    XP bar
                                </ProgressLabel>
                                <ProgressValue />
                            </Progress>
                        </div>

                        <div className="grid w-full grid-cols-2 items-stretch gap-2 min-[400px]:grid-cols-4">
                            {stages.map((stage, index) => (
                                <div key={index} className="flex min-h-0 h-full">
                                    <Tooltip>
                                        <TooltipTrigger
                                            render={
                                                <div
                                                    className={cn(
                                                        'flex min-h-[6.25rem] w-full cursor-default flex-col items-center gap-2 rounded-lg border-2 p-2.5 text-center outline-none transition-colors motion-safe:hover:bg-muted/20 min-[400px]:min-h-[6.5rem]',
                                                        stage.locked &&
                                                            'border-dashed border-muted-foreground/40 bg-muted/15 grayscale-[0.15]',
                                                        stage.complete && 'border-success/70 bg-success/5',
                                                        !stage.complete &&
                                                            stage.isCurrent &&
                                                            'border-foreground/60 bg-card ring-1 ring-inset ring-primary/50',
                                                        !stage.complete &&
                                                            !stage.isCurrent &&
                                                            !stage.locked &&
                                                            'border-foreground/20 bg-muted/10'
                                                    )}
                                                >
                                                    <div
                                                        className={cn(
                                                            'flex size-10 shrink-0 items-center justify-center rounded-full transition-colors duration-200',
                                                            stage.complete &&
                                                                'bg-success/20 text-success ring-1 ring-inset ring-success/35',
                                                            !stage.complete &&
                                                                stage.isCurrent &&
                                                                'bg-primary text-primary-foreground motion-safe:[animation:referral-current-nudge_3s_ease-in-out_infinite]',
                                                            !stage.complete &&
                                                                !stage.isCurrent &&
                                                                !stage.locked &&
                                                                'bg-primary/12 text-primary ring-1 ring-inset ring-primary/20',
                                                            !stage.complete &&
                                                                stage.locked &&
                                                                'bg-muted/80 text-muted-foreground ring-1 ring-inset ring-border/60'
                                                        )}
                                                    >
                                                        {stage.complete ? (
                                                            <IconCheck className="size-[22px] shrink-0 stroke-[2.5]" />
                                                        ) : stage.locked ? (
                                                            <IconLock className="size-[22px] shrink-0 opacity-95" />
                                                        ) : stage.isCurrent ? (
                                                            <IconSparkles className="size-[22px] shrink-0" />
                                                        ) : (
                                                            <span className="text-sm font-black tabular-nums leading-none">
                                                                {index + 1}
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div className="flex w-full min-h-[2.75rem] flex-1 flex-col items-center justify-center px-0.5">
                                                        <span className="line-clamp-2 w-full text-[10px] font-extrabold leading-snug tracking-tight text-foreground">
                                                            {stage.label}
                                                        </span>
                                                    </div>
                                                </div>
                                            }
                                        />
                                        <TooltipContent
                                            side="top"
                                            className="max-w-[260px] border border-primary/25 bg-card text-center text-card-foreground font-medium shadow-none"
                                        >
                                            {stage.hint}
                                        </TooltipContent>
                                    </Tooltip>
                                </div>
                            ))}
                        </div>
                    </CardContent>
                </Card>
            </>
        </TooltipProvider>
    )
}
