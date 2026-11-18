import { z } from "zod";

export const secureStoreGetInput = z.object({ key: z.string() });
export const secureStoreSetInput = z.object({
  key: z.string(),
  value: z.string(),
});
export const secureStoreRemoveInput = z.object({ key: z.string() });
