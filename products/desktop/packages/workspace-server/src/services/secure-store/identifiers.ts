export const SECURE_STORE_SERVICE = Symbol.for(
  "posthog.workspace.secureStoreService",
);

export interface ISecureStoreService {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  clear(): void;
}
