/**
 * Per-integration-kind host allowlist for outbound MCP requests.
 *
 * Threat model: a bundle author can write any URL into `mcps[].url` plus an
 * `auth.integration` reference. Without a host check the runner would attach
 * the team's connected OAuth token (Slack, Linear, etc.) to whatever URL the
 * author wanted — exfiltration. `assertSafeExternalMcpUrl` already blocks
 * private / loopback hosts, but a public `evil.com` would still slip through
 * the SSRF floor. This registry closes that gap by binding each integration
 * kind to a fixed list of host patterns.
 *
 * The registry is **append-only**: adding a kind is one entry; removing or
 * narrowing a kind's hosts breaks existing bundles that already authored
 * against the wider set.
 *
 * `integrationRef` shape — `<kind>:<integration_id>` (e.g. `slack:T01XXX`).
 * Mirrors `IntegrationStore.resolveForSpec` which keys the credential map
 * the same way. An unknown kind always returns false (fail-closed).
 */

import { IntegrationHostValidator } from '../loop/mcp-clients'

export const INTEGRATION_HOST_REGISTRY: Record<string, ReadonlyArray<RegExp>> = {
    // Slack: REST API (`slack.com/api/...`) and the future hosted MCP server.
    // Both `chat.postMessage` and friends route through `slack.com`; subdomain
    // variants are kept explicit so a typo in `slackcompany.com` can't
    // accidentally match.
    slack: [/^slack\.com$/, /^api\.slack\.com$/, /^mcp\.slack\.com$/],
}

/**
 * Build a validator from a host registry. Parses `<kind>:<id>` and matches
 * `url.host` against the registry's patterns for that kind. Unknown kinds
 * and unmatched hosts return false; the caller refuses to attach the bearer.
 */
export function makeIntegrationHostValidator(
    registry: Record<string, ReadonlyArray<RegExp>> = INTEGRATION_HOST_REGISTRY
): IntegrationHostValidator {
    return (integrationRef: string, url: URL): boolean => {
        const colon = integrationRef.indexOf(':')
        if (colon <= 0) {
            return false
        }
        const kind = integrationRef.slice(0, colon)
        const patterns = registry[kind]
        if (!patterns) {
            return false
        }
        return patterns.some((p) => p.test(url.host))
    }
}
