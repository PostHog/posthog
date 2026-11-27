// The Google OAuth endpoints that every Google OAuth kind shares. Each kind has its own app and scope.

import type { AuthorizeSpec, TokenInfoSpec, TokenSpec } from './schema'

export const GOOGLE_AUTHORIZE: Omit<AuthorizeSpec, 'scope'> = {
    url: 'https://accounts.google.com/o/oauth2/v2/auth',
    // `prompt=consent` forces the consent screen. Without it, Google sends no refresh token on a reconnect.
    extraParams: [
        ['access_type', 'offline'],
        ['prompt', 'consent'],
    ],
    pkce: false,
    opaqueState: false,
}

export const GOOGLE_TOKEN: TokenSpec = {
    url: 'https://oauth2.googleapis.com/token',
    auth: 'client_secret_post',
}

export const GOOGLE_TOKEN_INFO: TokenInfoSpec = {
    idPath: 'sub',
    namePath: 'email',
    request: { url: 'https://openidconnect.googleapis.com/v1/userinfo', configFields: ['sub', 'email'] },
}

export const GOOGLE_USERINFO_EMAIL_SCOPE = 'https://www.googleapis.com/auth/userinfo.email'
