import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const CLIENT_INFO = { name: "posthog-code", version: "1.0.0" };

export async function probeMcpInitialize(
  url: string,
  configuredHeaders: ReadonlyArray<{ name: string; value: string }>,
  markerHeaderName: string,
  probeHeaderName: string,
  timeoutMs = 2_000,
): Promise<boolean> {
  const headers = new Headers();
  for (const header of configuredHeaders) {
    headers.set(header.name, header.value);
  }
  if (
    configuredHeaders.some(
      (header) => header.name.toLowerCase() === markerHeaderName,
    )
  ) {
    headers.set(probeHeaderName, "1");
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => {
    controller.abort(new Error("MCP initialize probe timed out."));
  }, timeoutMs);
  const transport = new StreamableHTTPClientTransport(new URL(url), {
    requestInit: { headers },
  });
  const client = new Client(CLIENT_INFO, { capabilities: {} });

  try {
    await client.connect(transport, {
      signal: controller.signal,
      timeout: timeoutMs,
      maxTotalTimeout: timeoutMs,
    });
    return true;
  } catch (error) {
    if (controller.signal.aborted) {
      throw controller.signal.reason ?? error;
    }
    return false;
  } finally {
    clearTimeout(timeout);
    if (transport.sessionId) {
      await transport.terminateSession().catch(() => undefined);
    }
    await client.close().catch(() => undefined);
    await transport.close().catch(() => undefined);
  }
}
