import { z } from "zod";

export const connectivityStatusOutput = z.object({
  isOnline: z.boolean(),
});

export type ConnectivityStatusOutput = z.infer<typeof connectivityStatusOutput>;

export const ConnectivityEvent = {
  StatusChange: "status-change",
} as const;

export interface ConnectivityEvents {
  [ConnectivityEvent.StatusChange]: ConnectivityStatusOutput;
}
