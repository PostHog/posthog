import * as crypto from "node:crypto";

const MAX_PROBE_RESPONSE_BYTES = 256 * 1024;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isMatchingInitializeResponse(
  value: unknown,
  requestId: string,
): boolean {
  return (
    isObject(value) &&
    value.jsonrpc === "2.0" &&
    value.id === requestId &&
    isObject(value.result) &&
    !("error" in value)
  );
}

function parseJsonCandidate(text: string, requestId: string): boolean {
  try {
    return isMatchingInitializeResponse(JSON.parse(text), requestId);
  } catch {
    return false;
  }
}

function hasMatchingSseEvent(text: string, requestId: string): boolean {
  for (const event of text.split(/\r?\n\r?\n/)) {
    const data = event
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (data && parseJsonCandidate(data, requestId)) return true;
  }
  return false;
}

async function readBoundedBody(
  response: Response,
  signal: AbortSignal,
): Promise<string> {
  if (!response.body) return "";
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  if (signal.aborted) throw signal.reason;
  const aborted = new Promise<never>((_resolve, reject) => {
    signal.addEventListener(
      "abort",
      () => reject(signal.reason ?? new Error("MCP probe timed out.")),
      { once: true },
    );
  });
  try {
    while (true) {
      const result = await Promise.race([reader.read(), aborted]);
      if (result.done) break;
      size += result.value.byteLength;
      if (size > MAX_PROBE_RESPONSE_BYTES) {
        throw new Error("MCP probe response is too large.");
      }
      chunks.push(result.value);
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(body);
}

export async function probeMcpInitialize(
  url: string,
  configuredHeaders: ReadonlyArray<{ name: string; value: string }>,
  markerHeaderName: string,
  probeHeaderName: string,
  timeoutMs = 2_000,
): Promise<boolean> {
  const requestId = crypto.randomUUID();
  const headers: Record<string, string> = {
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
  };
  for (const header of configuredHeaders) headers[header.name] = header.value;
  if (
    configuredHeaders.some(
      (header) => header.name.toLowerCase() === markerHeaderName,
    )
  ) {
    headers[probeHeaderName] = "1";
  }

  const signal = AbortSignal.timeout(timeoutMs);
  const response = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: requestId,
      method: "initialize",
      params: {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "posthog-code", version: "1.0.0" },
      },
    }),
    signal,
  });
  if (
    !response.ok ||
    response.headers.get("x-posthog-agent-plugin-proxy-error") === "1"
  ) {
    await response.body?.cancel().catch(() => undefined);
    return false;
  }

  const body = await readBoundedBody(response, signal);
  const contentType = response.headers.get("content-type") ?? "";
  return contentType.includes("text/event-stream")
    ? hasMatchingSseEvent(body, requestId)
    : parseJsonCandidate(body, requestId);
}
