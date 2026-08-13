export interface WarmTaskLease {
  taskId: string;
  runId: string;
}

export interface WarmTaskLeaseKeyParts {
  repository?: string | null;
  repositories?: string[];
  branch?: string | null;
  runtimeAdapter?: string | null;
  model?: string | null;
  reasoningEffort?: string | null;
  sandboxEnvironmentId?: string | null;
  customImageId?: string | null;
}

export function buildWarmTaskLeaseKey(parts: WarmTaskLeaseKeyParts): string {
  return [
    (parts.repositories ?? (parts.repository ? [parts.repository] : [])).join(
      ",",
    ),
    parts.branch ?? "",
    parts.runtimeAdapter ?? "",
    parts.model ?? "",
    parts.sandboxEnvironmentId ?? "",
    parts.customImageId ?? "",
  ].join(":");
}

let currentLease: { key: string; lease: WarmTaskLease } | null = null;

export function rememberWarmTaskLease(key: string, lease: WarmTaskLease): void {
  currentLease = { key, lease };
}

export function takeWarmTaskLease(
  parts: WarmTaskLeaseKeyParts,
): WarmTaskLease | null {
  const stored = currentLease;
  currentLease = null;
  if (!stored || stored.key !== buildWarmTaskLeaseKey(parts)) {
    return null;
  }
  return stored.lease;
}
