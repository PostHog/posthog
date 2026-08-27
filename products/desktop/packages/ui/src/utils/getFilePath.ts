import { resolveServiceOptional } from "@posthog/di/container";

export interface FilePathResolver {
  resolve(file: File): string | undefined;
}

export const FILE_PATH_RESOLVER = Symbol.for("posthog.ui.FilePathResolver");

export function getFilePath(file: File): string {
  const resolved =
    resolveServiceOptional<FilePathResolver>(FILE_PATH_RESOLVER)?.resolve(file);
  if (resolved) return resolved;
  return (file as File & { path?: string }).path ?? "";
}
