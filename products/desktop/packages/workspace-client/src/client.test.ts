import { afterEach, describe, expect, it, vi } from "vitest";
import { createLazyWorkspaceClient, type WorkspaceConnection } from "./client";

const connA: WorkspaceConnection = {
  url: "http://127.0.0.1:1111",
  secret: "secret-a",
};
const connB: WorkspaceConnection = {
  url: "http://127.0.0.1:2222",
  secret: "secret-b",
};

const trpcResponse = (data: unknown) =>
  new Response(JSON.stringify([{ result: { data: { json: data } } }]), {
    headers: { "content-type": "application/json" },
  });

describe("createLazyWorkspaceClient", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not resolve a connection until an operation starts", () => {
    const getConnection = vi.fn().mockResolvedValue(connA);
    const client = createLazyWorkspaceClient(getConnection);

    Reflect.get(client.fs, "readAbsoluteFile");

    expect(getConnection).not.toHaveBeenCalled();
  });

  it("resolves the current connection for each query", async () => {
    let current = connA;
    const getConnection = vi.fn(async () => current);
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(trpcResponse("first"))
      .mockResolvedValueOnce(trpcResponse("second"));
    vi.stubGlobal("fetch", fetch);
    const client = createLazyWorkspaceClient(getConnection);

    await expect(
      client.fs.readAbsoluteFile.query({ filePath: "/tmp/first" }),
    ).resolves.toBe("first");
    current = connB;
    await expect(
      client.fs.readAbsoluteFile.query({ filePath: "/tmp/second" }),
    ).resolves.toBe("second");

    expect(getConnection).toHaveBeenCalledTimes(2);
    const firstUrl = new URL(String(fetch.mock.calls[0]?.[0]));
    const secondUrl = new URL(String(fetch.mock.calls[1]?.[0]));
    expect(firstUrl.origin).toBe(connA.url);
    expect(secondUrl.origin).toBe(connB.url);
    expect(
      new Headers(fetch.mock.calls[0]?.[1]?.headers).get("x-workspace-secret"),
    ).toBe(connA.secret);
    expect(
      new Headers(fetch.mock.calls[1]?.[1]?.headers).get("x-workspace-secret"),
    ).toBe(connB.secret);
  });

  it("resolves a connection when a subscription starts", async () => {
    const getConnection = vi.fn().mockRejectedValue(new Error("start failed"));
    const onError = vi.fn();
    const client = createLazyWorkspaceClient(getConnection);

    const subscription = client.fileWatcher.watch.subscribe(
      { repoPath: "/tmp/repo" },
      { onError },
    );

    await vi.waitFor(() => expect(getConnection).toHaveBeenCalledOnce());
    await vi.waitFor(() => expect(onError).toHaveBeenCalledOnce());
    subscription.unsubscribe();
  });
});
