import { useValues } from 'kea'

import { LemonCard, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { Badge, cn } from 'lib/ui/quill'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { REFERRAL_MILESTONE_COUNT, referralInviteMilestonesCompleted } from './referralInviteMilestoneModel'
import { ReferralInviteMilestoneProgress } from './ReferralInviteMilestoneProgress'
import { ReferralsAttributedSignupsIntro } from './ReferralsAttributedSignupsIntro'
import { ReferralAttributedSignupRow, referralsSceneLogic } from './referralsSceneLogic'
import { ReferralsSignupLinkPanel } from './ReferralsSignupLinkPanel'

/** Above this count, attributed signups render as a sortable table instead of cards. */
const ATTRIBUTED_SIGNUPS_COMPACT_MAX = 9

function sortAttributedSignupsBySignupDateDesc(rows: ReferralAttributedSignupRow[]): ReferralAttributedSignupRow[] {
    return [...rows].sort((a, b) => {
        const au = a.signedUpAt ? dayjs(a.signedUpAt).unix() : 0
        const bu = b.signedUpAt ? dayjs(b.signedUpAt).unix() : 0
        return bu - au
    })
}

function ReferralAttributedSignupMilestoneBadge({ row }: { row: ReferralAttributedSignupRow }): JSX.Element {
    const done = referralInviteMilestonesCompleted(row)
    const isMaxed = done >= REFERRAL_MILESTONE_COUNT
    return (
        <Badge
            variant={isMaxed ? 'success' : 'default'}
            className={cn(
                'h-auto min-h-0 shrink-0 border px-2 py-0.5 text-xs tabular-nums font-semibold leading-snug ring-0',
                isMaxed ? 'border-foreground/15' : 'border-border text-foreground'
            )}
            title={`${done} of ${REFERRAL_MILESTONE_COUNT} milestones complete`}
            data-attr="referral-attributed-milestones-count"
        >
            {done}/{REFERRAL_MILESTONE_COUNT}
        </Badge>
    )
}

export function ReferralsScene(): JSX.Element {
    const { attributedSignupRows, referralsLoading, referralShareUrl } = useValues(referralsSceneLogic)

    const rows = attributedSignupRows ?? []
    const rowCount = rows.length
    const showCompactAttributedList = !referralsLoading && rowCount > 0 && rowCount <= ATTRIBUTED_SIGNUPS_COMPACT_MAX

    const columns: LemonTableColumns<ReferralAttributedSignupRow> = [
        {
            title: 'Organization',
            key: 'invited_organization',
            render: (_, row) => (
                <span
                    className="block truncate max-w-md font-medium text-default"
                    title={`${row.invitedOrganizationName} (${row.invitedOrganizationId})`}
                    data-attr="referral-attributed-org-name"
                >
                    {row.invitedOrganizationName}
                </span>
            ),
            sorter: (a, b) => a.invitedOrganizationName.localeCompare(b.invitedOrganizationName),
        },
        {
            title: 'Signed-up user',
            key: 'signed_up_user',
            render: (_, row) => {
                if (row.signedUpUserDisplayName) {
                    return (
                        <span className="block truncate max-w-xs" data-attr="referral-attributed-user-name">
                            {row.signedUpUserDisplayName}
                        </span>
                    )
                }
                return '–'
            },
            sorter: (a, b) => {
                const an = a.signedUpUserDisplayName || ''
                const bn = b.signedUpUserDisplayName || ''
                const c = an.localeCompare(bn)
                if (c !== 0) {
                    return c
                }
                return (a.signedUpUserId ?? -1) - (b.signedUpUserId ?? -1)
            },
        },
        {
            title: 'Signup date',
            key: 'signup_date',
            defaultSortOrder: -1,
            render: (_, row) => (row.signedUpAt ? <TZLabel time={row.signedUpAt} /> : '–'),
            sorter: (a, b) => {
                const au = a.signedUpAt ? dayjs(a.signedUpAt).unix() : 0
                const bu = b.signedUpAt ? dayjs(b.signedUpAt).unix() : 0
                return au - bu
            },
        },
        {
            title: 'Milestones',
            key: 'milestones',
            render: (_, row) => <ReferralAttributedSignupMilestoneBadge row={row} />,
            sorter: (a, b) => {
                const ad = referralInviteMilestonesCompleted(a)
                const bd = referralInviteMilestonesCompleted(b)
                if (ad !== bd) {
                    return ad - bd
                }
                return a.invitedOrganizationId.localeCompare(b.invitedOrganizationId)
            },
        },
    ]

    const copyDisabledReason = !referralShareUrl ? 'Loading user…' : undefined

    return (
        <SceneContent translate="no">
            <SceneTitleSection
                name={sceneConfigurations[Scene.Referrals].name}
                description={sceneConfigurations[Scene.Referrals].description}
                resourceType={{ type: 'link' }}
            />

            <ReferralsSignupLinkPanel referralShareUrl={referralShareUrl} copyDisabledReason={copyDisabledReason} />

            <header className="mb-4 flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
                <div className="min-w-0">
                    <h2 className="m-0 text-[15px] font-semibold text-default">Keep track of your flock</h2>
                    <p className="m-0 mt-1 text-secondary text-sm">
                        Every org that joins through your link lands here, with who signed up and when.
                    </p>
                </div>
                {(referralsLoading || rowCount > 0) && (
                    <div className="flex shrink-0 flex-col items-end justify-end text-right">
                        {referralsLoading && rowCount === 0 ? (
                            <span className="text-secondary text-sm tabular-nums">Loading…</span>
                        ) : (
                            <span
                                className="text-default text-sm font-semibold tabular-nums leading-snug"
                                data-attr="referral-attributed-total-count"
                            >
                                {rowCount} {rowCount === 1 ? 'referral' : 'referrals'}
                            </span>
                        )}
                    </div>
                )}
            </header>
            {showCompactAttributedList ? (
                <div className="flex flex-col gap-10 sm:gap-12" role="list">
                    {sortAttributedSignupsBySignupDateDesc(rows).map((row) => (
                        <article
                            key={`${row.socialReferralId}:${row.invitedOrganizationId}`}
                            className="flex flex-col gap-4 overflow-hidden rounded-lg border border-primary bg-surface-primary shadow-sm sm:gap-5"
                            data-attr="referral-attributed-signup-card"
                            role="listitem"
                        >
                            <div className="flex flex-wrap items-start justify-between gap-3 px-4 pb-3 pt-5 sm:px-5 sm:pb-4 sm:pt-6">
                                <div className="min-w-0 flex-1 space-y-1">
                                    <p
                                        className="m-0 font-semibold text-default leading-snug"
                                        title={`${row.invitedOrganizationName} (${row.invitedOrganizationId})`}
                                        data-attr="referral-attributed-org-name"
                                    >
                                        {row.invitedOrganizationName}
                                    </p>
                                    <p className="m-0 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-secondary text-sm">
                                        <span data-attr="referral-attributed-user-name">
                                            {row.signedUpUserDisplayName ?? '–'}
                                        </span>
                                        <span className="text-secondary opacity-60" aria-hidden>
                                            ·
                                        </span>
                                        <span data-attr="referral-attributed-signup-date">
                                            {row.signedUpAt ? <TZLabel time={row.signedUpAt} /> : '–'}
                                        </span>
                                    </p>
                                </div>
                                <div className="flex flex-col items-end gap-1">
                                    <span className="text-[11px] font-medium text-secondary">Milestones</span>
                                    <ReferralAttributedSignupMilestoneBadge row={row} />
                                </div>
                            </div>
                            <div className="px-4 pb-5 sm:px-5 sm:pb-6">
                                <ReferralInviteMilestoneProgress
                                    firstEventSent={row.firstEventSent}
                                    layout="embedded"
                                />
                            </div>
                        </article>
                    ))}
                </div>
            ) : referralsLoading || rowCount > 0 ? (
                <LemonTable
                    columns={columns}
                    dataSource={rows}
                    loading={!!referralsLoading}
                    defaultSorting={{ columnKey: 'signup_date', order: -1 }}
                    rowKey={(row) => `${row.socialReferralId}:${row.invitedOrganizationId}`}
                    expandable={{
                        rowExpandable: () => true,
                        expandedRowRender: (row) => (
                            <ReferralInviteMilestoneProgress firstEventSent={row.firstEventSent} />
                        ),
                    }}
                />
            ) : (
                <LemonCard hoverEffect={false} className="shadow-sm border-primary">
                    <ReferralsAttributedSignupsIntro
                        referralShareUrl={referralShareUrl}
                        copyDisabledReason={copyDisabledReason}
                    />
                </LemonCard>
            )}
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: ReferralsScene,
    logic: referralsSceneLogic,
}
