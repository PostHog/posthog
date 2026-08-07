import type {
  LocalMcpServerDescriptor,
  LocalMcpTransport,
} from "@posthog/shared";
import { z } from "zod";

const localMcpTransportSchema: z.ZodType<LocalMcpTransport> = z.union([
  z.object({
    type: z.enum(["http", "sse"]),
    url: z.string(),
    headers: z.record(z.string(), z.string()).optional(),
  }),
  z.object({
    type: z.literal("stdio"),
    command: z.string(),
    args: z.array(z.string()).optional(),
  }),
  z.object({ type: z.literal("unknown") }),
]);

export const localMcpServerDescriptorSchema: z.ZodType<LocalMcpServerDescriptor> =
  z.object({
    name: z.string(),
    scope: z.enum(["user", "project"]),
    transport: localMcpTransportSchema,
  });

export const listLocalMcpServersInput = z.object({
  cwd: z.string().optional(),
});

export const listLocalMcpServersOutput = z.array(
  localMcpServerDescriptorSchema,
);
