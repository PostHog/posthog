import type http from "node:http";
import { hopByHop } from "../proxy-stream/hop-by-hop";

export type Body = Buffer<ArrayBuffer>;

export const STRIPPED_REQUEST_HEADERS = new Set([
  "authorization",
  "x-api-key",
  "api-key",
  "anthropic-auth-token",
  "proxy-authorization",
  "content-length",
  "transfer-encoding",
  "cookie",
]);

export const STRIPPED_RESPONSE_HEADERS = new Set([
  "transfer-encoding",
  "content-encoding",
  "content-length",
  "set-cookie",
  "www-authenticate",
]);

export const MAX_BODY_BYTES = 16 * 1024 * 1024;
export const PROXY_TIMEOUTS = {
  bodyMs: 60_000,
  // Non-streaming calls can run for minutes before the first byte; the ALB in
  // front of the gateway closes at 300s, so this only catches a wedged connection.
  headersMs: 10 * 60_000,
  // A buffered refusal or model list is small, so a stall here is a fault.
  bufferedBodyMs: 30_000,
};

/** Request header names never forwarded upstream, given the inbound Connection value. */
export function strippedRequestHeaders(
  connection: string | string[] | undefined,
): Set<string> {
  return new Set([
    "host",
    ...STRIPPED_REQUEST_HEADERS,
    ...hopByHop(connection),
  ]);
}

export function jsonError(
  res: http.ServerResponse,
  status: number,
  error: Record<string, string>,
  extraHeaders: Record<string, string> = {},
): void {
  if (res.headersSent) {
    res.end();
    return;
  }
  res.writeHead(status, {
    "content-type": "application/json",
    ...extraHeaders,
  });
  res.end(JSON.stringify({ error }));
}

export function responseHeaders(
  response: Response,
  stripped: ReadonlySet<string> = STRIPPED_RESPONSE_HEADERS,
): Record<string, string> {
  const hop = hopByHop(response.headers.get("connection"));
  const headers: Record<string, string> = {};
  response.headers.forEach((value: string, key: string) => {
    const name = key.toLowerCase();
    if (stripped.has(name) || hop.has(name)) return;
    headers[key] = value;
  });
  return headers;
}

export function readBody(
  req: http.IncomingMessage,
): Promise<Body | "too_large" | "timeout" | "aborted"> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    let size = 0;
    let settled = false;
    const finish = (result: Body | "too_large" | "timeout" | "aborted") => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      req.off("data", onData);
      // Drain the rest so the socket can carry the error response.
      if (typeof result === "string") req.resume();
      resolve(result);
    };
    const timer = setTimeout(() => finish("timeout"), PROXY_TIMEOUTS.bodyMs);
    const onData = (chunk: Buffer) => {
      size += chunk.byteLength;
      if (size > MAX_BODY_BYTES) {
        finish("too_large");
        return;
      }
      chunks.push(chunk);
    };
    req.on("data", onData);
    req.on("end", () => finish(Buffer.concat(chunks)));
    req.on("error", () => finish("aborted"));
    req.on("aborted", () => finish("aborted"));
  });
}
