import type { ReactElement } from 'react'

import { deleteAccountUrl, openLegalLink, PRIVACY_POLICY_URL, SUPPORT_URL, TERMS_URL } from '@/lib/legalLinks'

import { SettingsGroup } from './SettingsGroup'
import { SettingsLinkRow } from './SettingsLinkRow'

/** `accountHost` is the signed-in host, or null in demo mode and when signed out, which hides Delete account. */
export function LegalGroup({ accountHost }: { accountHost: string | null }): ReactElement {
    return (
        <SettingsGroup
            title="Legal and support"
            footer={accountHost ? 'Delete account opens your PostHog account settings in the browser.' : undefined}
            testID="settings-legal"
        >
            <SettingsLinkRow
                label="Privacy policy"
                onPress={() => openLegalLink('privacy', PRIVACY_POLICY_URL, 'settings')}
                testID="settings-privacy"
            />
            <SettingsLinkRow
                label="Terms"
                onPress={() => openLegalLink('terms', TERMS_URL, 'settings')}
                testID="settings-terms"
            />
            <SettingsLinkRow
                label="Support"
                onPress={() => openLegalLink('support', SUPPORT_URL, 'settings')}
                testID="settings-support"
            />
            {accountHost ? (
                <SettingsLinkRow
                    label="Delete account"
                    onPress={() => openLegalLink('delete_account', deleteAccountUrl(accountHost), 'settings')}
                    testID="settings-delete-account"
                />
            ) : null}
        </SettingsGroup>
    )
}
