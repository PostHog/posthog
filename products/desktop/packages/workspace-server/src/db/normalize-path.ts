import { resolve } from "node:path";

export function normalizeDirectoryPath(input: string): string {
  return resolve(input);
}
