import { openTrackedUrl } from './openTrackedUrl'

export const PRIVACY_POLICY_URL = 'https://posthog.com/privacy'
export const TERMS_URL = 'https://posthog.com/terms'
// The support options page the web app opens for people without in-app support. It lists the channels per plan.
export const SUPPORT_URL = 'https://posthog.com/docs/support-options?utm_medium=in-product&utm_campaign=mobile-app'

/** The web app's Delete account section. The app cannot delete an account itself. */
export function deleteAccountUrl(host: string): string {
    return `${host}/settings/user-danger-zone`
}

export type LegalLink = 'privacy' | 'terms' | 'support' | 'delete_account'

export function openLegalLink(link: LegalLink, url: string, surface: 'sign_in' | 'settings' | 'ai_consent'): void {
    void openTrackedUrl(url, 'mobile_legal_link_opened', { link, surface })
}
