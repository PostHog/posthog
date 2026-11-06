import { z } from "zod";

const registeredFolderSchema = z.object({
  id: z.string(),
  path: z.string(),
  name: z.string(),
  remoteUrl: z.string().nullable(),
  lastAccessed: z.string(),
  createdAt: z.string(),
  /**
   * Root of the main checkout when this folder is a linked git worktree
   * (`git worktree add`), null for a main clone. Computed at list time.
   */
  mainRepoPath: z.string().nullable().optional(),
});

export const registeredFolderWithExistsSchema = registeredFolderSchema.extend({
  exists: z.boolean().optional(),
});

export const getFoldersOutput = z.array(registeredFolderWithExistsSchema);

export const addFolderInput = z.object({
  folderPath: z.string().min(2, "Folder path must be a valid directory path"),
  remoteUrl: z.string().min(1).optional(),
});

export const addFolderOutput = registeredFolderWithExistsSchema;

export const removeFolderInput = z.object({
  folderId: z.string(),
});

export const updateFolderAccessedInput = z.object({
  folderId: z.string(),
});

export type RegisteredFolder = z.infer<typeof registeredFolderWithExistsSchema>;
export const repositoryLookupResult = z
  .object({
    id: z.string(),
    path: z.string(),
  })
  .nullable();

export const getRepositoryByRemoteUrlInput = z.object({
  remoteUrl: z.string(),
});
