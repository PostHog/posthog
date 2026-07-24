import { z } from "zod";

export const secureStoreGetInput = z.object({ key: z.string() });
export const secureStoreSetInput = z.object({
  key: z.string(),
  value: z.string(),
});
export const secureStoreRemoveInput = z.object({ key: z.string() });

export type SecureStoreGetInput = z.infer<typeof secureStoreGetInput>;
export type SecureStoreSetInput = z.infer<typeof secureStoreSetInput>;
export type SecureStoreRemoveInput = z.infer<typeof secureStoreRemoveInput>;
