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

export function ReferralsScene(): JSX.Element {
    const { attributedSignupRows, referralsLoading, referralShareUrl } = useValues(referralsSceneLogic)

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
            render: (_, row) => {
                const done = referralInviteMilestonesCompleted(row)
                const isMaxed = done >= REFERRAL_MILESTONE_COUNT
                return (
                    <Badge
                        variant={isMaxed ? 'success' : 'default'}
                        className={cn(
                            'h-auto min-h-0 border px-2 py-0.5 text-xs tabular-nums font-semibold leading-snug ring-0',
                            isMaxed ? 'border-foreground/15' : 'border-border text-foreground'
                        )}
                        title={`${done} of ${REFERRAL_MILESTONE_COUNT} milestones complete`}
                        data-attr="referral-attributed-milestones-count"
                    >
                        {done}/{REFERRAL_MILESTONE_COUNT}
                    </Badge>
                )
            },
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
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Referrals].name}
                description={sceneConfigurations[Scene.Referrals].description}
                resourceType={{ type: 'link' }}
            />

            <ReferralsSignupLinkPanel referralShareUrl={referralShareUrl} copyDisabledReason={copyDisabledReason} />

            <header className="mb-4">
                <h2 className="m-0 text-[15px] font-semibold text-default">Keep track of your flock</h2>
                <p className="m-0 mt-1 text-secondary text-sm">
                    Every org that joins through your link lands here, with who signed up and when.
                </p>
            </header>
            {referralsLoading || (attributedSignupRows?.length ?? 0) > 0 ? (
                <LemonTable
                    columns={columns}
                    dataSource={attributedSignupRows ?? []}
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
