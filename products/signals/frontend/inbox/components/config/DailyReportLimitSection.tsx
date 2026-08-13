import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'

const CARD_CLASS = 'flex flex-col gap-2 rounded border border-primary bg-surface-primary px-2.5 py-2'

/**
 * Daily report limit card for the inbox usage rail: a per-project cap on how many reports may
 * surface per project-timezone day. Setting the field is the enforcement switch: once today's
 * count reaches it, signal ingestion, scout runs, and report research pause until local midnight.
 * Unlike the PR usage widget above it, this renders without billing data, since the cap is a team
 * setting rather than a billing product, so it is the primary home for the limit-reached state.
 */
export function DailyReportLimitSection(): JSX.Element {
    const {
        teamConfig,
        teamConfigLoading,
        teamConfigUpdating,
        draftMaxReportsPerDay,
        saveMaxReportsPerDayDisabledReason,
        maxReportsPerDay,
        reportsGeneratedToday,
        dailyReportLimitReached,
    } = useValues(signalTeamConfigLogic)
    const { setDraftMaxReportsPerDay, saveDraftMaxReportsPerDay } = useActions(signalTeamConfigLogic)

    if (!teamConfig && teamConfigLoading) {
        return (
            <div className={CARD_CLASS}>
                <LemonSkeleton className="h-3 w-32" />
                <LemonSkeleton className="h-8 w-full" />
            </div>
        )
    }

    return (
        <div className={CARD_CLASS}>
            <div className="flex items-center justify-between gap-1.5">
                <span className="text-[13px] font-semibold text-default">Daily report limit</span>
                {maxReportsPerDay != null && (
                    <span className="text-xs text-secondary tabular-nums">
                        {Math.min(reportsGeneratedToday, maxReportsPerDay)} / {maxReportsPerDay} today
                    </span>
                )}
            </div>
            <div className="flex items-center gap-2">
                <LemonInput
                    type="number"
                    min={1}
                    step={1}
                    placeholder="No limit"
                    value={draftMaxReportsPerDay ?? undefined}
                    onChange={(value) => setDraftMaxReportsPerDay(value ?? null)}
                    onPressEnter={saveDraftMaxReportsPerDay}
                    size="small"
                    fullWidth
                />
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={saveDraftMaxReportsPerDay}
                    loading={teamConfigUpdating}
                    disabledReason={saveMaxReportsPerDayDisabledReason ?? undefined}
                >
                    Save
                </LemonButton>
            </div>
            <span className="text-xs text-secondary">
                Pause new report generation after this many reports in a day. Leave empty for no limit.
            </span>
            {dailyReportLimitReached && (
                <span className="text-xs font-medium text-danger">
                    Daily report limit reached. New reports resume at midnight in your project's timezone.
                </span>
            )}
        </div>
    )
}
