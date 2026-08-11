import { describe, expect, it } from "vitest";
import type { IDefaultAdditionalDirectoryRepository } from "../../db/repositories/default-additional-directory-repository";
import type { IWorkspaceRepository } from "../../db/repositories/workspace-repository";
import { AdditionalDirectoriesService } from "./additional-directories";

function makeDefaultsRepo(initial: string[] = []) {
  let dirs = [...initial];
  const repo: Pick<
    IDefaultAdditionalDirectoryRepository,
    "list" | "add" | "remove"
  > = {
    list: () => [...dirs],
    add: (p) => {
      if (!dirs.includes(p)) dirs.push(p);
    },
    remove: (p) => {
      dirs = dirs.filter((d) => d !== p);
    },
  };
  return repo as IDefaultAdditionalDirectoryRepository;
}

function makeWorkspacesRepo() {
  const byTask = new Map<string, string[]>();
  const repo: Pick<
    IWorkspaceRepository,
    | "getAdditionalDirectories"
    | "addAdditionalDirectory"
    | "removeAdditionalDirectory"
  > = {
    getAdditionalDirectories: (taskId) => [...(byTask.get(taskId) ?? [])],
    addAdditionalDirectory: (taskId, p) => {
      const list = byTask.get(taskId) ?? [];
      if (!list.includes(p)) list.push(p);
      byTask.set(taskId, list);
    },
    removeAdditionalDirectory: (taskId, p) => {
      byTask.set(
        taskId,
        (byTask.get(taskId) ?? []).filter((d) => d !== p),
      );
    },
  };
  return repo as IWorkspaceRepository;
}

describe("AdditionalDirectoriesService", () => {
  it("lists, adds, and removes default directories", () => {
    const service = new AdditionalDirectoriesService(
      makeDefaultsRepo(["/a"]),
      makeWorkspacesRepo(),
    );
    expect(service.listDefaults()).toEqual(["/a"]);
    service.addDefault("/b");
    expect(service.listDefaults()).toEqual(["/a", "/b"]);
    service.removeDefault("/a");
    expect(service.listDefaults()).toEqual(["/b"]);
  });

  it("scopes per-task directories to their task", () => {
    const service = new AdditionalDirectoriesService(
      makeDefaultsRepo(),
      makeWorkspacesRepo(),
    );
    service.addForTask("task-1", "/x");
    service.addForTask("task-2", "/y");
    expect(service.listForTask("task-1")).toEqual(["/x"]);
    expect(service.listForTask("task-2")).toEqual(["/y"]);
    service.removeForTask("task-1", "/x");
    expect(service.listForTask("task-1")).toEqual([]);
    expect(service.listForTask("task-2")).toEqual(["/y"]);
  });
});
