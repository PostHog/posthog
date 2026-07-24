import http from "node:http";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type StreamProgress, streamBodyToResponse } from "./proxy-stream";

describe("streamBodyToResponse", () => {
  let server: http.Server | undefined;

  afterEach(async () => {
    await new Promise<void>((resolve) => {
      if (!server) return resolve();
      server.close(() => resolve());
    });
    server = undefined;
  });

  async function serve(
    handler: (res: http.ServerResponse) => void,
  ): Promise<string> {
    const srv = http.createServer((_req, res) => handler(res));
    server = srv;
    await new Promise<void>((resolve) =>
      srv.listen(0, "127.0.0.1", () => resolve()),
    );
    const addr = srv.address() as { port: number };
    return `http://127.0.0.1:${addr.port}`;
  }

  it("copies the body to the response and ends it", async () => {
    const url = await serve((res) => {
      res.writeHead(200, { "content-type": "text/event-stream" });
      void streamBodyToResponse(
        new Response("data: one\n\ndata: two\n\n").body,
        res,
      );
    });

    const res = await fetch(url);

    expect(await res.text()).toBe("data: one\n\ndata: two\n\n");
  });

  it("ends the response when the body is null", async () => {
    const url = await serve((res) => {
      res.writeHead(200);
      void streamBodyToResponse(null, res);
    });

    const res = await fetch(url);

    expect(await res.text()).toBe("");
  });

  it("cancels the upstream body when the client disconnects", async () => {
    let cancelled = false;
    const url = await serve((res) => {
      res.writeHead(200, { "content-type": "text/event-stream" });
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode("data: one\n\n"));
          // Never closes — simulates an in-flight upstream stream.
        },
        cancel() {
          cancelled = true;
        },
      });
      void streamBodyToResponse(body, res);
    });

    const clientAbort = new AbortController();
    const res = await fetch(url, { signal: clientAbort.signal });
    await res.body?.getReader().read();
    clientAbort.abort();

    await vi.waitFor(() => {
      expect(cancelled).toBe(true);
    });
  });

  it("counts streamed bytes into progress", async () => {
    const progress: StreamProgress = { bytesWritten: 0 };
    const payload = "data: one\n\ndata: two\n\n";
    const url = await serve((res) => {
      res.writeHead(200);
      void streamBodyToResponse(new Response(payload).body, res, progress);
    });

    await fetch(url).then((r) => r.text());

    await vi.waitFor(() => {
      expect(progress.bytesWritten).toBe(
        new TextEncoder().encode(payload).byteLength,
      );
    });
  });

  it("accumulates bytes across multiple chunks", async () => {
    const progress: StreamProgress = { bytesWritten: 0 };
    const url = await serve((res) => {
      res.writeHead(200);
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          for (const chunk of ["aaaa", "bbbbbb", "cc"]) {
            controller.enqueue(new TextEncoder().encode(chunk));
          }
          controller.close();
        },
      });
      void streamBodyToResponse(body, res, progress);
    });

    await fetch(url).then((r) => r.text());

    await vi.waitFor(() => {
      expect(progress.bytesWritten).toBe(12);
    });
  });

  it("leaves progress at zero for a null body", async () => {
    const progress: StreamProgress = { bytesWritten: 0 };
    const url = await serve((res) => {
      res.writeHead(200);
      void streamBodyToResponse(null, res, progress);
    });

    await fetch(url).then((r) => r.text());

    expect(progress.bytesWritten).toBe(0);
  });
});
