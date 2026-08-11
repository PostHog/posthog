import * as http from "node:http";
import type { Socket } from "node:net";
import { injectable } from "inversify";

export interface WaitForCallbackOptions {
  port: number;
  /** Pathname to match, e.g. "/mcp-oauth-complete". */
  path: string;
  timeoutMs: number;
  signal?: AbortSignal;
  /** Fired once the server is listening — the caller opens the browser here. */
  onListening?: () => void;
  /** Decides whether to render the success or error page from the params. */
  successWhen: (params: URLSearchParams) => boolean;
}

/**
 * Local HTTP server that receives an OAuth-style redirect in development and
 * resolves with the callback query params. Owns the Node `http.Server`,
 * connection tracking, timeout, and the served HTML. Rejects on timeout /
 * cancellation (via `signal`) / listen error.
 */
@injectable()
export class McpCallbackServer {
  waitForCallback(options: WaitForCallbackOptions): Promise<URLSearchParams> {
    const { port, path, timeoutMs, signal, onListening, successWhen } = options;

    return new Promise<URLSearchParams>((resolve, reject) => {
      const connections = new Set<Socket>();
      let settled = false;

      const cleanup = () => {
        clearTimeout(timeoutId);
        signal?.removeEventListener("abort", onAbort);
        for (const conn of connections) {
          conn.destroy();
        }
        connections.clear();
        server.close();
      };

      const finish = (action: () => void) => {
        if (settled) return;
        settled = true;
        cleanup();
        action();
      };

      const server = http.createServer((req, res) => {
        if (!req.url) {
          res.writeHead(400);
          res.end();
          return;
        }

        const url = new URL(req.url, `http://localhost:${port}`);

        if (url.pathname === path) {
          const ok = successWhen(url.searchParams);
          res.writeHead(200, { "Content-Type": "text/html" });
          res.end(callbackHtml(ok ? "success" : "error"));
          finish(() => resolve(url.searchParams));
        } else {
          res.writeHead(404);
          res.end();
        }
      });

      server.on("connection", (conn) => {
        connections.add(conn);
        conn.on("close", () => connections.delete(conn));
      });

      const timeoutId = setTimeout(() => {
        finish(() => reject(new Error("MCP OAuth authorization timed out")));
      }, timeoutMs);

      const onAbort = () => {
        finish(() => reject(new Error("MCP OAuth flow cancelled")));
      };

      if (signal) {
        if (signal.aborted) {
          finish(() => reject(new Error("MCP OAuth flow cancelled")));
          return;
        }
        signal.addEventListener("abort", onAbort, { once: true });
      }

      server.on("error", (error) => {
        finish(() =>
          reject(
            new Error(`Failed to start callback server: ${error.message}`),
          ),
        );
      });

      server.listen(port, () => {
        onListening?.();
      });
    });
  }
}

function callbackHtml(status: "success" | "error"): string {
  const titles = {
    success: "Authorization successful!",
    error: "Authorization failed",
  };
  const messages = {
    success: "You can close this window and return to the PostHog desktop app.",
    error: "You can close this window and return to the PostHog desktop app.",
  };

  return `<!DOCTYPE html>
<html class="radix-themes" data-is-root-theme="true" data-accent-color="orange" data-gray-color="slate" data-has-background="true" data-panel-background="translucent" data-radius="none" data-scaling="100%">
  <head>
    <meta charset="utf-8">
    <title>${titles[status]}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@radix-ui/themes@3.1.6/styles.css">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
      @layer utilities {
        .text-gray-12 { color: var(--gray-12); }
        .text-gray-11 { color: var(--gray-11); }
        .bg-gray-1 { background-color: var(--gray-1); }
      }
    </style>
  </head>
  <body class="dark bg-gray-1 h-screen overflow-hidden flex flex-col items-center justify-center m-0 gap-2">
    <h1 class="text-gray-12 text-xl font-semibold">${titles[status]}</h1>
    <p class="text-gray-11 text-sm">${messages[status]}</p>
    <script>setTimeout(() => window.close(), 500);</script>
  </body>
</html>`;
}
