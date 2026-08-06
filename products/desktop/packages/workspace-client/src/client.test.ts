import { describe, expect, it, vi } from "vitest";
import {
  createReconnectingWorkspaceClient,
  type WorkspaceClient,
  type WorkspaceConnection,
} from "./client";

const connA: WorkspaceConnection = {
  url: "http://127.0.0.1:1111",
  secret: "secret-a",
};
const connB: WorkspaceConnection = {
  url: "http://127.0.0.1:2222",
  secret: "secret-b",
};

function makeFakeClient(name: string): WorkspaceClient {
  return { name } as unknown as WorkspaceClient;
}

describe("createReconnectingWorkspaceClient", () => {
  it("builds one client per connection and reuses it across accesses", () => {
    const buildClient = vi.fn(() => makeFakeClient("a"));
    const client = createReconnectingWorkspaceClient(() => connA, buildClient);

    expect(Reflect.get(client, "name")).toBe("a");
    expect(Reflect.get(client, "name")).toBe("a");
    expect(buildClient).toHaveBeenCalledTimes(1);
    expect(buildClient).toHaveBeenCalledWith(connA);
  });

  it("rebuilds the client when the connection changes (server respawn)", () => {
    let current = connA;
    const buildClient = vi
      .fn()
      .mockReturnValueOnce(makeFakeClient("a"))
      .mockReturnValueOnce(makeFakeClient("b"));
    const client = createReconnectingWorkspaceClient(
      () => current,
      buildClient,
    );

    expect(Reflect.get(client, "name")).toBe("a");
    current = connB;
    expect(Reflect.get(client, "name")).toBe("b");
    expect(buildClient).toHaveBeenCalledTimes(2);
    expect(buildClient).toHaveBeenLastCalledWith(connB);
  });

  it("keeps using the last known client while the server is down", () => {
    let current: WorkspaceConnection | null = connA;
    const buildClient = vi.fn(() => makeFakeClient("a"));
    const client = createReconnectingWorkspaceClient(
      () => current,
      buildClient,
    );

    expect(Reflect.get(client, "name")).toBe("a");
    current = null;
    expect(Reflect.get(client, "name")).toBe("a");
    expect(buildClient).toHaveBeenCalledTimes(1);
  });

  it("throws when accessed before any connection is established", () => {
    const buildClient = vi.fn();
    const client = createReconnectingWorkspaceClient(() => null, buildClient);

    expect(() => Reflect.get(client, "name")).toThrow(
      "workspace-server connection is not established yet",
    );
    expect(buildClient).not.toHaveBeenCalled();
  });
});
