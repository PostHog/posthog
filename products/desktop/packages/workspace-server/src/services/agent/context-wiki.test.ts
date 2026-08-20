import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { type AuthenticatedFetch, prepareContextWiki } from "./context-wiki";

const mockExecGit = vi.hoisted(() => vi.fn());

vi.mock("@posthog/git/git-exec", () => ({
  execGit: mockExecGit,
}));

const log = {
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
} as never;

// The module caches organization lookups and in-flight mounts by apiHost +
// projectId, so every test uses its own project to stay isolated.
let nextProjectId = 1;

const respondOk: AuthenticatedFetch = async (input) =>
  input.includes("/context_layer/export/")
    ? new Response(
        JSON.stringify({
          url: "https://storage.test/bundle",
          head_sha: "head1",
        }),
        { status: 200 },
      )
    : new Response(JSON.stringify({ organization: "org-1" }), { status: 200 });

function makeOptions(
  overrides: { authenticatedFetch?: AuthenticatedFetch } = {},
) {
  return {
    apiHost: "https://app.posthog.test",
    projectId: nextProjectId++,
    cacheDir: fs.mkdtempSync(path.join(os.tmpdir(), "context-wiki-test-")),
    log,
    authenticatedFetch: overrides.authenticatedFetch ?? respondOk,
  };
}

function bundleStream(chunks: () => Iterable<Uint8Array>): ReadableStream {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks()) {
        controller.enqueue(chunk);
      }
      controller.close();
    },
  });
}

describe("prepareContextWiki", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // A clone has to leave the staging directory behind for the rename.
    mockExecGit.mockImplementation(async (args: string[]) => {
      if (args[0] === "clone") {
        await fs.promises.mkdir(args[3], { recursive: true });
      }
      return { exitCode: 0, stdout: "", stderr: "" };
    });
  });

  it.each([
    ["the wiki was never enabled", 404],
    ["the organization has private projects", 403],
    ["the request failed", 500],
  ])("returns null when %s", async (_label, status) => {
    const options = makeOptions({
      authenticatedFetch: async (input) =>
        input.includes("/context_layer/export/")
          ? new Response("", { status })
          : new Response(JSON.stringify({ organization: "org-1" }), {
              status: 200,
            }),
    });

    await expect(prepareContextWiki(options)).resolves.toBeNull();
    expect(mockExecGit).not.toHaveBeenCalled();
  });

  it("aborts a bundle that streams past the size cap and leaves no partial file", async () => {
    // One 10 MB buffer pushed 21 times: 210 MB counted, 10 MB resident.
    const chunk = new Uint8Array(10_000_000);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        body: bundleStream(function* () {
          for (let index = 0; index < 21; index++) {
            yield chunk;
          }
        }),
      })),
    );
    const options = makeOptions();

    await expect(prepareContextWiki(options)).resolves.toBeNull();

    expect(fs.readdirSync(options.cacheDir, { recursive: true })).not.toEqual(
      expect.arrayContaining([expect.stringContaining(".bundle")]),
    );
    vi.unstubAllGlobals();
  });

  it("shares one clone between concurrent callers for the same organization", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        body: bundleStream(function* () {
          yield new Uint8Array([1, 2, 3]);
        }),
      })),
    );
    const options = makeOptions();

    // A second caller must not rm -rf the checkout the first is about to hand
    // to a session, so both have to await the same preparation.
    const [first, second] = await Promise.all([
      prepareContextWiki(options),
      prepareContextWiki(options),
    ]);

    expect(first).not.toBeNull();
    expect(second).toEqual(first);
    expect(
      mockExecGit.mock.calls.filter((call) => call[0][0] === "clone"),
    ).toHaveLength(1);
    vi.unstubAllGlobals();
  });
});
