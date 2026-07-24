import type { WorkspaceMode } from "@posthog/shared";
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { RegisteredFolder } from "../../folders/types";
import {
  areReposReady,
  type RepoSelection,
  type RepoSelectionInput,
  resolveRepoSelectionForFolder,
  useInitialRepoSelectionFromFolderId,
} from "./useInitialRepoSelectionFromFolderId";

const folder = (
  id: string,
  path: string,
  remoteUrl: string | null = null,
): RegisteredFolder => ({
  id,
  path,
  name: id,
  remoteUrl,
  lastAccessed: "2026-05-21T00:00:00Z",
  createdAt: "2026-05-21T00:00:00Z",
});

describe("resolveRepoSelectionForFolder", () => {
  it.each<{
    name: string;
    input: Omit<RepoSelectionInput, "folder"> & { remoteUrl: string | null };
    expected: RepoSelection;
  }>([
    {
      name: "cloud-capable folder in cloud mode: prefill cloud repo, keep cloud",
      input: {
        remoteUrl: "posthog/posthog",
        repositories: ["posthog/posthog"],
        reposLoaded: true,
        currentMode: "cloud",
        lastUsedLocalMode: "local",
      },
      expected: {
        directory: "/repos/a",
        cloudRepository: "posthog/posthog",
        nextMode: undefined,
      },
    },
    {
      name: "cloud-capable folder in local mode: seed cloud repo, keep local",
      input: {
        remoteUrl: "posthog/posthog",
        repositories: ["posthog/posthog"],
        reposLoaded: true,
        currentMode: "local",
        lastUsedLocalMode: "local",
      },
      expected: {
        directory: "/repos/a",
        cloudRepository: "posthog/posthog",
        nextMode: undefined,
      },
    },
    {
      name: "lower-cases the remote slug before matching",
      input: {
        remoteUrl: "PostHog/PostHog",
        repositories: ["posthog/posthog"],
        reposLoaded: true,
        currentMode: "cloud",
        lastUsedLocalMode: "local",
      },
      expected: {
        directory: "/repos/a",
        cloudRepository: "posthog/posthog",
        nextMode: undefined,
      },
    },
    {
      name: "local-only folder in cloud mode: switch to last-used local mode",
      input: {
        remoteUrl: null,
        repositories: ["posthog/posthog"],
        reposLoaded: true,
        currentMode: "cloud",
        lastUsedLocalMode: "worktree",
      },
      expected: {
        directory: "/repos/a",
        cloudRepository: undefined,
        nextMode: "worktree",
      },
    },
    {
      name: "remote not in the integrations list: not cloud-capable, switch to local",
      input: {
        remoteUrl: "acme/private",
        repositories: ["posthog/posthog"],
        reposLoaded: true,
        currentMode: "cloud",
        lastUsedLocalMode: "local",
      },
      expected: {
        directory: "/repos/a",
        cloudRepository: undefined,
        nextMode: "local",
      },
    },
    {
      name: "ignores legacy single-segment remote values",
      input: {
        remoteUrl: "posthog",
        repositories: ["posthog"],
        reposLoaded: true,
        currentMode: "cloud",
        lastUsedLocalMode: "local",
      },
      expected: {
        directory: "/repos/a",
        cloudRepository: undefined,
        nextMode: "local",
      },
    },
    {
      name: "loaded with empty repositories (no integration): switch to local in cloud",
      input: {
        remoteUrl: "posthog/posthog",
        repositories: [],
        reposLoaded: true,
        currentMode: "cloud",
        lastUsedLocalMode: "local",
      },
      expected: {
        directory: "/repos/a",
        cloudRepository: undefined,
        nextMode: "local",
      },
    },
    {
      name: "not loaded: never switch mode (await the integrations list)",
      input: {
        remoteUrl: null,
        repositories: [],
        reposLoaded: false,
        currentMode: "cloud",
        lastUsedLocalMode: "local",
      },
      expected: {
        directory: "/repos/a",
        cloudRepository: undefined,
        nextMode: undefined,
      },
    },
    {
      name: "local-only folder already in a local mode: keep mode, no switch",
      input: {
        remoteUrl: null,
        repositories: ["posthog/posthog"],
        reposLoaded: true,
        currentMode: "worktree",
        lastUsedLocalMode: "local",
      },
      expected: {
        directory: "/repos/a",
        cloudRepository: undefined,
        nextMode: undefined,
      },
    },
    {
      name: "most recent run was local while in cloud: switch to local (keep cloud repo seeded)",
      input: {
        remoteUrl: "posthog/posthog",
        repositories: ["posthog/posthog"],
        reposLoaded: true,
        currentMode: "cloud",
        lastUsedLocalMode: "local",
        mostRecentEnvironment: "local",
      },
      expected: {
        directory: "/repos/a",
        cloudRepository: "posthog/posthog",
        nextMode: "local",
      },
    },
    {
      name: "most recent run was cloud while in local: switch to cloud",
      input: {
        remoteUrl: "posthog/posthog",
        repositories: ["posthog/posthog"],
        reposLoaded: true,
        currentMode: "local",
        lastUsedLocalMode: "local",
        mostRecentEnvironment: "cloud",
      },
      expected: {
        directory: "/repos/a",
        cloudRepository: "posthog/posthog",
        nextMode: "cloud",
      },
    },
    {
      name: "most recent run was cloud but repo not cloud-capable, in local: stay local",
      input: {
        remoteUrl: null,
        repositories: ["posthog/posthog"],
        reposLoaded: true,
        currentMode: "local",
        lastUsedLocalMode: "local",
        mostRecentEnvironment: "cloud",
      },
      expected: {
        directory: "/repos/a",
        cloudRepository: undefined,
        nextMode: undefined,
      },
    },
    {
      name: "most recent run was cloud but repo not cloud-capable, in cloud: drop to local",
      input: {
        remoteUrl: null,
        repositories: ["posthog/posthog"],
        reposLoaded: true,
        currentMode: "cloud",
        lastUsedLocalMode: "worktree",
        mostRecentEnvironment: "cloud",
      },
      expected: {
        directory: "/repos/a",
        cloudRepository: undefined,
        nextMode: "worktree",
      },
    },
  ])("$name", ({ input: { remoteUrl, ...rest }, expected }) => {
    expect(
      resolveRepoSelectionForFolder({
        folder: folder("a", "/repos/a", remoteUrl),
        ...rest,
      }),
    ).toEqual(expected);
  });
});

describe("areReposReady", () => {
  it.each([
    {
      name: "still loading: not ready",
      isLoadingRepos: true,
      repositoriesCount: 5,
      hasGithubIntegration: true,
      expected: false,
    },
    {
      name: "loaded with repos: ready",
      isLoadingRepos: false,
      repositoriesCount: 5,
      hasGithubIntegration: true,
      expected: true,
    },
    {
      name: "loaded, empty, no integration (settled empty): ready",
      isLoadingRepos: false,
      repositoriesCount: 0,
      hasGithubIntegration: false,
      expected: true,
    },
    {
      name: "loaded, empty, but has integration (transient window): not ready",
      isLoadingRepos: false,
      repositoriesCount: 0,
      hasGithubIntegration: true,
      expected: false,
    },
  ])(
    "$name",
    ({ isLoadingRepos, repositoriesCount, hasGithubIntegration, expected }) => {
      expect(
        areReposReady({
          isLoadingRepos,
          repositoriesCount,
          hasGithubIntegration,
        }),
      ).toBe(expected);
    },
  );
});

type HookArgs = {
  folderId: string | undefined;
  requestId?: string;
  folders: RegisteredFolder[];
  repositories: string[];
  reposLoaded: boolean;
  currentMode: WorkspaceMode;
  mostRecentEnvironment?: "local" | "cloud";
};

function renderRepoSelectionHook(initial: HookArgs) {
  const setSelectedDirectory = vi.fn();
  const setSelectedRepository = vi.fn();
  const setWorkspaceMode = vi.fn();
  const utils = renderHook(
    (props: HookArgs) =>
      useInitialRepoSelectionFromFolderId({
        folderId: props.folderId,
        requestId: props.requestId,
        folders: props.folders,
        repositories: props.repositories,
        reposLoaded: props.reposLoaded,
        currentMode: props.currentMode,
        lastUsedLocalMode: "local",
        mostRecentEnvironment: props.mostRecentEnvironment,
        setSelectedDirectory,
        setSelectedRepository,
        switchWorkspaceMode: setWorkspaceMode,
      }),
    { initialProps: initial },
  );
  return {
    ...utils,
    setSelectedDirectory,
    setSelectedRepository,
    setWorkspaceMode,
  };
}

describe("useInitialRepoSelectionFromFolderId", () => {
  it("syncs the directory immediately and the cloud repo once repos load", () => {
    const { rerender, setSelectedDirectory, setSelectedRepository } =
      renderRepoSelectionHook({
        folderId: "a",
        folders: [folder("a", "/repos/a", "posthog/posthog")],
        repositories: [],
        reposLoaded: false,
        currentMode: "cloud",
      });
    // Directory applies right away, even before the integrations list loads.
    expect(setSelectedDirectory).toHaveBeenCalledExactlyOnceWith("/repos/a");
    expect(setSelectedRepository).not.toHaveBeenCalled();

    rerender({
      folderId: "a",
      folders: [folder("a", "/repos/a", "posthog/posthog")],
      repositories: ["posthog/posthog"],
      reposLoaded: true,
      currentMode: "cloud",
    });
    expect(setSelectedRepository).toHaveBeenCalledExactlyOnceWith(
      "posthog/posthog",
    );
    // Directory is not re-applied (once per folderId).
    expect(setSelectedDirectory).toHaveBeenCalledTimes(1);
  });

  it("switches into cloud when the repo's most recent run was cloud", () => {
    const { setWorkspaceMode, setSelectedRepository } = renderRepoSelectionHook(
      {
        folderId: "a",
        folders: [folder("a", "/repos/a", "posthog/posthog")],
        repositories: ["posthog/posthog"],
        reposLoaded: true,
        currentMode: "local",
        mostRecentEnvironment: "cloud",
      },
    );
    expect(setWorkspaceMode).toHaveBeenCalledExactlyOnceWith("cloud");
    expect(setSelectedRepository).toHaveBeenCalledExactlyOnceWith(
      "posthog/posthog",
    );
  });

  it("switches to local when the repo's most recent run was local while in cloud", () => {
    const { setWorkspaceMode } = renderRepoSelectionHook({
      folderId: "a",
      folders: [folder("a", "/repos/a", "posthog/posthog")],
      repositories: ["posthog/posthog"],
      reposLoaded: true,
      currentMode: "cloud",
      mostRecentEnvironment: "local",
    });
    expect(setWorkspaceMode).toHaveBeenCalledExactlyOnceWith("local");
  });

  it("switches to local mode for a local-only folder once repos load", () => {
    const { setWorkspaceMode, setSelectedRepository } = renderRepoSelectionHook(
      {
        folderId: "a",
        folders: [folder("a", "/repos/a", null)],
        repositories: ["posthog/posthog"],
        reposLoaded: true,
        currentMode: "cloud",
      },
    );
    expect(setWorkspaceMode).toHaveBeenCalledExactlyOnceWith("local");
    expect(setSelectedRepository).not.toHaveBeenCalled();
  });

  it("waits for folders to load before syncing the directory", () => {
    const { rerender, setSelectedDirectory } = renderRepoSelectionHook({
      folderId: "a",
      folders: [],
      repositories: [],
      reposLoaded: false,
      currentMode: "local",
    });
    // The target folder isn't in the list yet: bail without marking the sync done.
    expect(setSelectedDirectory).not.toHaveBeenCalled();

    // Once folders load, the prefill fires (the guard ref was left unset).
    rerender({
      folderId: "a",
      folders: [folder("a", "/repos/a")],
      repositories: [],
      reposLoaded: false,
      currentMode: "local",
    });
    expect(setSelectedDirectory).toHaveBeenCalledExactlyOnceWith("/repos/a");
  });

  it("does not re-sync when folders changes but folderId stays the same", () => {
    const { rerender, setSelectedDirectory } = renderRepoSelectionHook({
      folderId: "a",
      folders: [folder("a", "/repos/a")],
      repositories: [],
      reposLoaded: false,
      currentMode: "local",
    });
    expect(setSelectedDirectory).toHaveBeenCalledExactlyOnceWith("/repos/a");

    // Simulate the user picking a different folder afterward; the changed list must
    // not clobber their pick by re-syncing from the original folderId.
    rerender({
      folderId: "a",
      folders: [folder("a", "/repos/a"), folder("b", "/repos/picked")],
      repositories: [],
      reposLoaded: false,
      currentMode: "local",
    });
    expect(setSelectedDirectory).toHaveBeenCalledTimes(1);
  });

  it("re-syncs when folderId changes", () => {
    const folders = [
      folder("a", "/repos/a", "posthog/a"),
      folder("b", "/repos/b", "posthog/b"),
    ];
    const { rerender, setSelectedDirectory, setSelectedRepository } =
      renderRepoSelectionHook({
        folderId: "a",
        folders,
        repositories: ["posthog/a", "posthog/b"],
        reposLoaded: true,
        currentMode: "cloud",
      });
    expect(setSelectedDirectory).toHaveBeenLastCalledWith("/repos/a");
    expect(setSelectedRepository).toHaveBeenLastCalledWith("posthog/a");

    rerender({
      folderId: "b",
      folders,
      repositories: ["posthog/a", "posthog/b"],
      reposLoaded: true,
      currentMode: "cloud",
    });
    expect(setSelectedDirectory).toHaveBeenLastCalledWith("/repos/b");
    expect(setSelectedRepository).toHaveBeenLastCalledWith("posthog/b");
  });

  it("does nothing when folderId is undefined", () => {
    const { setSelectedDirectory, setSelectedRepository, setWorkspaceMode } =
      renderRepoSelectionHook({
        folderId: undefined,
        folders: [folder("a", "/repos/a", "posthog/posthog")],
        repositories: ["posthog/posthog"],
        reposLoaded: true,
        currentMode: "cloud",
      });
    expect(setSelectedDirectory).not.toHaveBeenCalled();
    expect(setSelectedRepository).not.toHaveBeenCalled();
    expect(setWorkspaceMode).not.toHaveBeenCalled();
  });

  it("re-syncs the same folderId after it is cleared to undefined", () => {
    const folders = [folder("a", "/repos/a", "posthog/a")];
    const repositories = ["posthog/a"];
    const { rerender, setSelectedDirectory } = renderRepoSelectionHook({
      folderId: "a",
      folders,
      repositories,
      reposLoaded: true,
      currentMode: "cloud",
    });
    expect(setSelectedDirectory).toHaveBeenCalledExactlyOnceWith("/repos/a");

    // Clearing folderId resets the guards so the same folder can prefill again.
    rerender({
      folderId: undefined,
      folders,
      repositories,
      reposLoaded: true,
      currentMode: "cloud",
    });
    expect(setSelectedDirectory).toHaveBeenCalledTimes(1);

    rerender({
      folderId: "a",
      folders,
      repositories,
      reposLoaded: true,
      currentMode: "cloud",
    });
    expect(setSelectedDirectory).toHaveBeenCalledTimes(2);
    expect(setSelectedDirectory).toHaveBeenLastCalledWith("/repos/a");
  });

  it("does not re-apply the cloud repo when repositories changes for the same folderId", () => {
    const folders = [folder("a", "/repos/a", "posthog/a")];
    const { rerender, setSelectedRepository } = renderRepoSelectionHook({
      folderId: "a",
      folders,
      repositories: ["posthog/a"],
      reposLoaded: true,
      currentMode: "cloud",
    });
    expect(setSelectedRepository).toHaveBeenCalledExactlyOnceWith("posthog/a");

    // A later integrations-list update must not clobber a repo the user edited.
    rerender({
      folderId: "a",
      folders,
      repositories: ["posthog/a", "posthog/b"],
      reposLoaded: true,
      currentMode: "cloud",
    });
    expect(setSelectedRepository).toHaveBeenCalledTimes(1);
  });

  it("reads the live mode (not the mount-time mode) for the deferred cloud decision", () => {
    const folders = [folder("a", "/repos/a", null)];
    const repositories: string[] = [];
    const { rerender, setWorkspaceMode } = renderRepoSelectionHook({
      folderId: "a",
      folders,
      repositories,
      reposLoaded: false,
      currentMode: "cloud",
    });
    expect(setWorkspaceMode).not.toHaveBeenCalled();

    // User leaves cloud while the integrations list is still loading.
    rerender({
      folderId: "a",
      folders,
      repositories,
      reposLoaded: false,
      currentMode: "local",
    });
    // Integrations settle: the decision reads the live "local" mode and must not
    // switch. Had it used the stale "cloud", it would fall back to a local mode.
    rerender({
      folderId: "a",
      folders,
      repositories,
      reposLoaded: true,
      currentMode: "local",
    });
    expect(setWorkspaceMode).not.toHaveBeenCalled();
  });

  it("re-syncs the same folderId when a new requestId arrives (repeat '+' click)", () => {
    const folders = [folder("a", "/repos/a", "posthog/a")];
    const repositories = ["posthog/a"];
    const { rerender, setSelectedDirectory } = renderRepoSelectionHook({
      folderId: "a",
      requestId: "req-1",
      folders,
      repositories,
      reposLoaded: true,
      currentMode: "local",
    });
    expect(setSelectedDirectory).toHaveBeenCalledExactlyOnceWith("/repos/a");

    // Same request re-rendering must not re-apply (user edits stay intact)...
    rerender({
      folderId: "a",
      requestId: "req-1",
      folders,
      repositories,
      reposLoaded: true,
      currentMode: "local",
    });
    expect(setSelectedDirectory).toHaveBeenCalledTimes(1);

    // ...but a fresh click on the same group's "+" issues a new requestId and
    // must re-select the folder's directory.
    rerender({
      folderId: "a",
      requestId: "req-2",
      folders,
      repositories,
      reposLoaded: true,
      currentMode: "local",
    });
    expect(setSelectedDirectory).toHaveBeenCalledTimes(2);
    expect(setSelectedDirectory).toHaveBeenLastCalledWith("/repos/a");
  });
});
