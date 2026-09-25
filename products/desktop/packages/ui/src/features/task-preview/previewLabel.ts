import type { TaskRunExposedPort } from "@posthog/shared/domain-types";

export function previewLabel(port: TaskRunExposedPort): string {
  return port.name ?? `Port ${port.port}`;
}
