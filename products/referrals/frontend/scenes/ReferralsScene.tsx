import { useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTable, LemonTableColumns, Spinner } from '@posthog/lemon-ui'

import { WavingHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ReferralAttributedSignupRow, referralsSceneLogic } from './referralsSceneLogic'

function ReferralsAttributedSignupsIntro({
    referralShareUrl,
    copyDisabledReason,
}: {
    referralShareUrl: string | null
    copyDisabledReason: string | undefined
}): JSX.Element {
    return (
        <div
            data-attr="referrals-attributed-signups-empty"
            className="flex flex-col-reverse sm:flex-row items-center justify-center gap-6 w-full max-w-[40rem] mx-auto"
        >
            <div className="flex flex-col gap-3 flex-1 min-w-0 text-center sm:text-left">
                <p className="m-0 text-[17px] font-semibold text-default leading-snug text-balance">
                    Your fan club spreadsheet is peacefully empty
                </p>
                <p className="m-0 text-secondary text-[15px] leading-relaxed text-balance">
                    The moment someone waltzes into PostHog through your link, they&apos;ll flop into this tidy little
                    list with timestamps and onboarding progress sprinkled in for context. Until then, air out your link
                    somewhere fun and check back like someone peeking into a warmed-up oven.
                </p>
                <div className="flex flex-wrap gap-2 justify-center sm:justify-start pt-0.5">
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconCopy />}
                        disabledReason={copyDisabledReason}
                        data-attr="referrals-empty-copy-link"
                        onClick={() => {
                            if (referralShareUrl) {
                                void copyToClipboard(referralShareUrl, 'referral link')
                            }
                        }}
                    >
                        Copy signup link
                    </LemonButton>
                </div>
            </div>
            <div className="shrink-0" aria-hidden>
                <WavingHog alt="" draggable={false} className="w-32 sm:w-[8.75rem] h-auto drop-shadow-md" />
            </div>
        </div>
    )
}

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
            title: 'Signup date',
            key: 'signup_date',
            render: (_, row) => (row.signedUpAt ? <TZLabel time={row.signedUpAt} /> : '–'),
            sorter: (a, b) => {
                const au = a.signedUpAt ? dayjs(a.signedUpAt).unix() : 0
                const bu = b.signedUpAt ? dayjs(b.signedUpAt).unix() : 0
                return au - bu
            },
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
            title: 'First event sent',
            key: 'first_event_sent',
            render: (_, row) => (
                <LemonTag type={row.firstEventSent ? 'success' : 'warning'} size="small">
                    {row.firstEventSent ? 'Yes' : 'No'}
                </LemonTag>
            ),
            sorter: (a, b) => Number(a.firstEventSent) - Number(b.firstEventSent),
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

            <LemonCard hoverEffect={false} className="mb-10 overflow-hidden shadow-sm border-primary p-0">
                <div className="relative">
                    <div
                        aria-hidden
                        className="absolute inset-y-0 left-0 w-1 rounded-l bg-gradient-to-b from-accent-active to-accent"
                    />
                    <div className="pl-6 pr-6 py-6 flex flex-col gap-5">
                        <div className="flex gap-4 min-w-0">
                            <div className="hidden sm:flex shrink-0 size-11 rounded-xl items-center justify-center bg-accent-highlight-secondary border border-accent/25">
                                <IconCopy className="text-accent text-xl" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <p className="m-0 text-lg font-semibold text-default tracking-tight">
                                    Your signup link
                                </p>
                                <p className="m-0 mt-1 text-secondary text-[15px] leading-snug max-w-2xl">
                                    Drop this wherever you yak about analytics: your team chat, timeline, sleepy
                                    newsletter footer, whichever. Anyone who swings by and joins shows up below as yours
                                    ✨
                                </p>
                            </div>
                        </div>

                        {!referralShareUrl ? (
                            <div className="flex items-center gap-2 text-secondary text-sm">
                                <Spinner />
                                Preparing your link…
                            </div>
                        ) : (
                            <div className="flex flex-col sm:flex-row gap-3 sm:items-stretch w-full max-w-2xl">
                                <div
                                    data-attr="social-referral-link"
                                    className="min-w-0 flex-1 rounded-lg border border-primary bg-fill-secondary px-3.5 py-3 shadow-[inset_0_1px_0_rgba(0,0,0,0.04)] dark:shadow-none"
                                >
                                    <span className="block font-mono text-[13px] text-default truncate select-all cursor-default">
                                        {referralShareUrl}
                                    </span>
                                </div>
                                <LemonButton
                                    type="primary"
                                    size="medium"
                                    className="shrink-0"
                                    icon={<IconCopy />}
                                    disabledReason={copyDisabledReason}
                                    data-attr="social-referral-copy"
                                    onClick={() => {
                                        if (referralShareUrl) {
                                            void copyToClipboard(referralShareUrl, 'referral link')
                                        }
                                    }}
                                >
                                    Copy link
                                </LemonButton>
                            </div>
                        )}
                    </div>
                </div>
            </LemonCard>

            <header className="mb-4">
                <h2 className="m-0 text-[15px] font-semibold text-default">Attributed signups</h2>
                <p className="m-0 mt-1 text-secondary text-sm">Referrals tracked from your link appear in this list.</p>
            </header>
            {referralsLoading || (attributedSignupRows?.length ?? 0) > 0 ? (
                <LemonTable
                    columns={columns}
                    dataSource={attributedSignupRows ?? []}
                    loading={!!referralsLoading}
                    rowKey={(row) => `${row.socialReferralId}:${row.invitedOrganizationId}`}
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
