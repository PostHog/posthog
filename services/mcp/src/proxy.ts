import { ApiClient } from "@/api/client";
import { env } from "@/lib/env";
import { isFeatureFlagEnabled } from "@/lib/posthog/flags";
import type { CloudRegion } from "@/tools/types";

const MCP_HONO_US_URL = "https://mcp.us.posthog.com";
const MCP_HONO_EU_URL = "https://mcp.eu.posthog.com";

type ResolvedUser = { distinctId: string; region: CloudRegion };

async function resolveUser(token: string): Promise<ResolvedUser | undefined> {
    const usBase = env.POSTHOG_API_BASE_URL || "https://us.posthog.com";
    const euBase = env.POSTHOG_API_BASE_URL || "https://eu.posthog.com";

    const [usResult, euResult] = await Promise.all([
        new ApiClient({ apiToken: token, baseUrl: usBase }).users().me(),
        new ApiClient({ apiToken: token, baseUrl: euBase }).users().me(),
    ]);

    if (usResult.success) {
        return { distinctId: usResult.data.distinct_id, region: "us" };
    }
    if (euResult.success) {
        return { distinctId: euResult.data.distinct_id, region: "eu" };
    }
    return undefined;
}

function getHonoTargetUrl(region: CloudRegion): string {
    if (env.MCP_HONO_URL) {
        return env.MCP_HONO_URL;
    }
    return region === "eu" ? MCP_HONO_EU_URL : MCP_HONO_US_URL;
}

export async function shouldProxyToHono(
    token: string,
): Promise<{ proxy: true; region: CloudRegion } | { proxy: false }> {
    try {
        const user = await resolveUser(token);
        if (!user) {
            console.info("[MCP proxy] could not resolve user, staying on CF");
            return { proxy: false };
        }
        const enabled = await isFeatureFlagEnabled("mcp-hono", user.distinctId);
        console.info(`[MCP proxy] flag mcp-hono=${enabled} for ${user.distinctId} (${user.region})`);
        if (enabled) {
            return { proxy: true, region: user.region };
        }
    } catch (err) {
        console.error("[MCP proxy] error evaluating proxy:", err);
    }
    return { proxy: false };
}

export function proxyToHono(
    request: Request,
    region: CloudRegion,
): Promise<Response> {
    const targetBase = getHonoTargetUrl(region);
    const targetUrl = new URL(request.url);
    const target = new URL(targetBase);
    targetUrl.hostname = target.hostname;
    targetUrl.protocol = target.protocol;
    targetUrl.port = target.port;

    console.info(`[MCP proxy] forwarding ${request.method} to ${targetUrl.toString()}`);

    return fetch(targetUrl.toString(), {
        method: request.method,
        headers: request.headers,
        body: request.body,
    });
}
