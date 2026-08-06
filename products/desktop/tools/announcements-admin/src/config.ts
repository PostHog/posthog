export const POSTHOG_HOST = "https://us.posthog.com";
export const PROJECT_ID = 2;
// The deploy origin is the OAuth identity (CIMD client_id derives from it),
// so it is baked in rather than read from window.location.
export const APP_ORIGIN = "https://desktop-announcements-admin.hosthog.dev";
export const CLIENT_ID = `${APP_ORIGIN}/.well-known/oauth-client-metadata.json`;
export const REDIRECT_URI = `${APP_ORIGIN}/oauth/callback`;
export const OAUTH_SCOPES = "feature_flag:read feature_flag:write";
