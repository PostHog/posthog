import posthog from 'posthog-js'

import { IconCopy, IconLetter } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

export interface WizardSpendAuditAccountOwner {
    name: string
    email: string
}

export type WizardSpendAuditOwnerContactPlacement = 'before_run' | 'after_run'

function firstName(name: string): string {
    return name.trim().split(/\s+/)[0] || name
}

function ownerMailto(
    owner: WizardSpendAuditAccountOwner,
    placement: WizardSpendAuditOwnerContactPlacement,
    organizationName: string | null,
    savingText: string | null
): string {
    const subject = organizationName ? `PostHog spend audit for ${organizationName}` : 'PostHog spend audit'
    const ask =
        placement === 'before_run'
            ? "I'd like to go through our PostHog spend with you."
            : savingText
              ? `We ran the PostHog spend audit. It estimates we could save about ${savingText} a month. Could we go through the recommendations together?`
              : 'We ran the PostHog spend audit. Could we go through the results together?'
    const body = `Hi ${firstName(owner.name)},\n\n${ask}\n`
    return `mailto:${owner.email}?${new URLSearchParams({ subject, body }).toString().replace(/\+/g, '%20')}`
}

export function WizardSpendAuditOwnerContact({
    owner,
    placement,
    organizationName,
    savingText = null,
}: {
    owner: WizardSpendAuditAccountOwner
    placement: WizardSpendAuditOwnerContactPlacement
    organizationName: string | null
    savingText?: string | null
}): JSX.Element {
    const name = firstName(owner.name)
    const track = (method: 'email' | 'copy'): void => {
        // pinned: analytics event name, renaming it breaks the account owner dashboards
        posthog.capture('spend audit account owner contacted', {
            placement,
            method,
            account_owner_email: owner.email,
        })
    }

    return (
        <div
            className="flex items-center gap-3 rounded border bg-surface-secondary p-3"
            data-attr="wizard-spend-audit-owner-contact"
        >
            <ProfilePicture user={{ first_name: owner.name, email: owner.email }} size="md" />
            <p className="m-0 min-w-0 flex-1 text-xs text-secondary">
                {placement === 'before_run'
                    ? `Prefer to talk it through? ${name}, your PostHog contact, can go through your spend with you.`
                    : `Want help acting on this? ${name}, your PostHog contact, can go through the results with you.`}
            </p>
            <div className="flex shrink-0 items-center gap-1">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconLetter />}
                    to={ownerMailto(owner, placement, organizationName, savingText)}
                    disableClientSideRouting
                    onClick={() => track('email')}
                    data-attr="wizard-spend-audit-owner-email"
                >
                    Email {name}
                </LemonButton>
                <LemonButton
                    size="small"
                    icon={<IconCopy />}
                    tooltip="Copy email address"
                    aria-label="Copy email address"
                    onClick={() => {
                        void copyToClipboard(owner.email, 'email address')
                        track('copy')
                    }}
                    data-attr="wizard-spend-audit-owner-copy"
                />
            </div>
        </div>
    )
}
