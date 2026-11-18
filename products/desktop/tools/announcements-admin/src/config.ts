export const POSTHOG_HOST = "https://us.posthog.com";
export const PROJECT_ID = 2;
// The CIMD client_id is the URL of the metadata document, published from
// PostHog/posthog.com (static/.well-known/oauth/desktop-announcements-admin/). It registers
// only the deployed origin's callback, so that origin is baked in rather than
// read from window.location.
const APP_ORIGIN = "https://desktop-announcements-admin.hosthog.dev";
export const CLIENT_ID =
  "https://posthog.com/.well-known/oauth/desktop-announcements-admin/client-metadata.json";
export const REDIRECT_URI = `${APP_ORIGIN}/oauth/callback`;
// user:read covers /api/users/@me/ for analytics identify. Also declared in
// the metadata document — keep the two lists in sync.
export const OAUTH_SCOPES = "feature_flag:read feature_flag:write user:read";
