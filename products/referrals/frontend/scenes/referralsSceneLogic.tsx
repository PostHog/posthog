import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { organizationLogic } from 'scenes/organizationLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Breadcrumb, UserType } from '~/types'

import type { referralsSceneLogicType } from './referralsSceneLogicType'

function socialReferralSignupUrl(distinctId: string): string {
    const url = new URL(urls.signup(), document.baseURI)
    url.searchParams.set('referral_program_id', distinctId)
    url.searchParams.set('utm_medium', 'in-product')
    url.searchParams.set('utm_campaign', 'social-referral')
    return url.href
}

export type SocialReferralRefereeInvite = {
    organization_id: string
    organization_name: string
    first_event_sent: boolean
    signed_up_at: string | null
    signed_up_user_id: number | null
    signed_up_user_display_name: string | null
}

export type SocialReferralListItem = {
    id: string
    organization: string
    user: number
    referee_state: Record<
        string,
        { first_event_sent?: boolean; signed_up_at?: string; signed_up_user_id?: number | null }
    >
    referee_invites?: SocialReferralRefereeInvite[]
    created_at: string
}

const REFEREE_STATE_ERRORS_KEY = 'errors'

function coerceSignedUpUserId(raw: unknown): number | null {
    if (raw === null || raw === undefined) {
        return null
    }
    if (typeof raw === 'number' && Number.isInteger(raw)) {
        return raw
    }
    if (typeof raw === 'string' && /^\d+$/.test(raw)) {
        return parseInt(raw, 10)
    }
    return null
}

export type ReferralAttributedSignupRow = {
    socialReferralId: string
    invitedOrganizationId: string
    invitedOrganizationName: string
    signedUpAt: string | null
    signedUpUserId: number | null
    signedUpUserDisplayName: string | null
    firstEventSent: boolean
    shareLinkCreatedAt: string
}

type PaginatedSocialReferrals = {
    count: number
    next: string | null
    previous: string | null
    results: SocialReferralListItem[]
}

export const referralsSceneLogic = kea<referralsSceneLogicType>([
    path(['products', 'referrals', 'referralsSceneLogic']),
    tabAwareScene(),
    connect(() => ({
        values: [organizationLogic, ['currentOrganizationId'], userLogic, ['user']],
    })),
    loaders(({ values }) => ({
        referrals: [
            [] as SocialReferralListItem[],
            {
                loadReferrals: async () => {
                    const orgId = values.currentOrganizationId
                    const data = await api.get<PaginatedSocialReferrals>(`api/organizations/${orgId}/social_referrals/`)
                    return data.results ?? []
                },
            },
        ],
    })),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Referrals,
                    name: sceneConfigurations[Scene.Referrals].name,
                    iconType: sceneConfigurations[Scene.Referrals].iconType || 'link',
                },
            ],
        ],
        referralShareUrl: [
            (s) => [s.user],
            (user: UserType | null): string | null =>
                user?.distinct_id ? socialReferralSignupUrl(user.distinct_id) : null,
        ],
        attributedSignupRows: [
            (s) => [s.referrals],
            (referrals: SocialReferralListItem[]): ReferralAttributedSignupRow[] => {
                const rows: ReferralAttributedSignupRow[] = []
                for (const item of referrals) {
                    const invites = item.referee_invites
                    if (invites?.length) {
                        for (const inv of invites) {
                            rows.push({
                                socialReferralId: item.id,
                                invitedOrganizationId: inv.organization_id,
                                invitedOrganizationName: inv.organization_name,
                                signedUpAt: inv.signed_up_at ?? null,
                                signedUpUserId: inv.signed_up_user_id ?? null,
                                signedUpUserDisplayName: inv.signed_up_user_display_name ?? null,
                                firstEventSent: inv.first_event_sent,
                                shareLinkCreatedAt: item.created_at,
                            })
                        }
                        continue
                    }

                    const state = item.referee_state
                    if (!state || typeof state !== 'object') {
                        continue
                    }
                    for (const [orgId, value] of Object.entries(state)) {
                        if (orgId === REFEREE_STATE_ERRORS_KEY) {
                            continue
                        }
                        if (value === null || typeof value !== 'object' || Array.isArray(value)) {
                            continue
                        }
                        const v = value as {
                            first_event_sent?: boolean
                            signed_up_at?: string
                            signed_up_user_id?: unknown
                        }
                        const signedRaw = v.signed_up_at
                        rows.push({
                            socialReferralId: item.id,
                            invitedOrganizationId: orgId,
                            invitedOrganizationName: 'Unknown organization',
                            signedUpAt: typeof signedRaw === 'string' && signedRaw ? signedRaw : null,
                            signedUpUserId: coerceSignedUpUserId(v.signed_up_user_id),
                            signedUpUserDisplayName: null,
                            firstEventSent: v.first_event_sent === true,
                            shareLinkCreatedAt: item.created_at,
                        })
                    }
                }
                rows.sort((a, b) => {
                    const nameCmp = a.invitedOrganizationName.localeCompare(b.invitedOrganizationName)
                    if (nameCmp !== 0) {
                        return nameCmp
                    }
                    const aSig = a.signedUpAt ? dayjs(a.signedUpAt).unix() : 0
                    const bSig = b.signedUpAt ? dayjs(b.signedUpAt).unix() : 0
                    if (aSig !== bSig) {
                        return bSig - aSig
                    }
                    const t = dayjs(b.shareLinkCreatedAt).unix() - dayjs(a.shareLinkCreatedAt).unix()
                    if (t !== 0) {
                        return t
                    }
                    const tUser = (a.signedUpUserDisplayName || '').localeCompare(b.signedUpUserDisplayName || '')
                    if (tUser !== 0) {
                        return tUser
                    }
                    return a.invitedOrganizationId.localeCompare(b.invitedOrganizationId)
                })
                return rows
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadReferrals()
    }),
])
