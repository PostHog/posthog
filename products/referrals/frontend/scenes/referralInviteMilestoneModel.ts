import type { ReferralAttributedSignupRow } from './referralsSceneLogic'

export const REFERRAL_MILESTONE_COUNT = 4

export type ReferralInviteStage = {
    label: string
    complete: boolean
    locked: boolean
    hint: string
    /** Unlockable next step they're working toward (excludes future roadmap-only milestones). */
    isCurrent: boolean
}

export function buildReferralInviteStages(firstEventSent: boolean): {
    stages: ReferralInviteStage[]
    completedCount: number
} {
    const stages: ReferralInviteStage[] = [
        {
            label: 'Invite accepted',
            complete: true,
            locked: false,
            hint: 'They created an org through your referral link.',
            isCurrent: false,
        },
        {
            label: 'First event sent',
            complete: firstEventSent,
            locked: false,
            hint: firstEventSent
                ? 'Their project has sent at least one event.'
                : 'Next up: their project sends its first event.',
            isCurrent: !firstEventSent,
        },
        {
            label: 'More milestones soon',
            complete: false,
            locked: true,
            hint: 'Another milestone—details coming soon.',
            isCurrent: false,
        },
        {
            label: 'More milestones soon',
            complete: false,
            locked: true,
            hint: 'Another milestone—details coming soon.',
            isCurrent: false,
        },
    ]
    const completedCount = stages.filter((s) => s.complete).length
    return { stages, completedCount }
}

export function referralInviteMilestonesCompleted(row: ReferralAttributedSignupRow): number {
    return buildReferralInviteStages(row.firstEventSent).completedCount
}
