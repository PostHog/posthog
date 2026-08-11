import { CLIENT_ID, OAUTH_SCOPES, POSTHOG_HOST, REDIRECT_URI } from "./config";

// Tokens live in localStorage so the session survives closing the tab; the
// site itself is employee-gated. Verifier/state are per-login-attempt only.
const TOKEN_KEY = "announcements-admin:token";
const EXPIRY_KEY = "announcements-admin:token-expiry";
const REFRESH_KEY = "announcements-admin:refresh-token";
const VERIFIER_KEY = "announcements-admin:verifier";
const STATE_KEY = "announcements-admin:state";

interface TokenResponse {
  access_token: string;
  expires_in?: number;
  refresh_token?: string;
}

function storeTokens(data: TokenResponse): void {
  localStorage.setItem(TOKEN_KEY, data.access_token);
  localStorage.setItem(
    EXPIRY_KEY,
    String(Date.now() + (data.expires_in ?? 3600) * 1000),
  );
  if (data.refresh_token) {
    localStorage.setItem(REFRESH_KEY, data.refresh_token);
  }
}

function randomString(bytes: number): string {
  const values = crypto.getRandomValues(new Uint8Array(bytes));
  return base64Url(values);
}

function base64Url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function sha256Base64Url(input: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(input),
  );
  return base64Url(new Uint8Array(digest));
}

export function getToken(): string | null {
  const token = localStorage.getItem(TOKEN_KEY);
  const expiry = Number(localStorage.getItem(EXPIRY_KEY) ?? 0);
  if (!token || Date.now() >= expiry) return null;
  return token;
}

/**
 * Valid access token, or one silently renewed from the stored refresh token.
 * Null means a fresh login is needed.
 */
export async function restoreSession(): Promise<string | null> {
  const token = getToken();
  if (token) return token;
  const refreshToken = localStorage.getItem(REFRESH_KEY);
  if (!refreshToken) return null;

  const response = await fetch(`${POSTHOG_HOST}/oauth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id: CLIENT_ID,
    }),
  });
  if (!response.ok) {
    logout();
    return null;
  }
  storeTokens((await response.json()) as TokenResponse);
  return getToken();
}

export function logout(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EXPIRY_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export async function beginLogin(): Promise<void> {
  const verifier = randomString(48);
  const state = randomString(24);
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);

  const url = new URL(`${POSTHOG_HOST}/oauth/authorize`);
  url.searchParams.set("client_id", CLIENT_ID);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("redirect_uri", REDIRECT_URI);
  url.searchParams.set("scope", OAUTH_SCOPES);
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", await sha256Base64Url(verifier));
  url.searchParams.set("code_challenge_method", "S256");
  window.location.assign(url.toString());
}

/**
 * Completes the authorization-code exchange on /oauth/callback. Returns true
 * when a token was stored, throws on a definite failure, false when the URL
 * carries no code (not a callback).
 */
export async function handleCallback(): Promise<boolean> {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  if (!code) return false;

  const expectedState = sessionStorage.getItem(STATE_KEY);
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  sessionStorage.removeItem(STATE_KEY);
  sessionStorage.removeItem(VERIFIER_KEY);
  if (!verifier || !expectedState || params.get("state") !== expectedState) {
    throw new Error("OAuth state mismatch — start the login again.");
  }

  const response = await fetch(`${POSTHOG_HOST}/oauth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: REDIRECT_URI,
      client_id: CLIENT_ID,
      code_verifier: verifier,
    }),
  });
  if (!response.ok) {
    throw new Error(`Token exchange failed (${response.status})`);
  }
  storeTokens((await response.json()) as TokenResponse);
  window.history.replaceState(null, "", "/");
  return true;
}
