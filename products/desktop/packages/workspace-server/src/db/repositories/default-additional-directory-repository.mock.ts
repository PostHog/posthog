import type { IDefaultAdditionalDirectoryRepository } from "./default-additional-directory-repository";

export interface MockDefaultAdditionalDirectoryRepository
  extends IDefaultAdditionalDirectoryRepository {
  _paths: string[];
}

export function createMockDefaultAdditionalDirectoryRepository(): MockDefaultAdditionalDirectoryRepository {
  let paths: string[] = [];
  return {
    get _paths() {
      return [...paths];
    },
    set _paths(value) {
      paths = [...value];
    },
    list: () => [...paths],
    add: (path) => {
      if (!paths.includes(path)) paths.push(path);
    },
    remove: (path) => {
      paths = paths.filter((p) => p !== path);
    },
  };
}
