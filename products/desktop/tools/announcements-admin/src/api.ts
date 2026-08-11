import { ANNOUNCEMENTS_FLAG } from "@posthog/shared";
import {
  type AnnouncementsPayload,
  announcementsPayloadSchema,
} from "@posthog/shared/announcements";
import { POSTHOG_HOST, PROJECT_ID } from "./config";

export interface FlagRecord {
  id: number;
  key: string;
  active: boolean;
  filters: {
    payloads?: Record<string, string>;
    [key: string]: unknown;
  };
}

async function request(token: string, path: string, init?: RequestInit) {
  const response = await fetch(`${POSTHOG_HOST}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    throw new Error(`PostHog API ${response.status}: ${await response.text()}`);
  }
  return response.json();
}

export async function fetchFlag(token: string): Promise<FlagRecord> {
  const data = (await request(
    token,
    `/api/projects/${PROJECT_ID}/feature_flags/?search=${ANNOUNCEMENTS_FLAG}`,
  )) as { results: FlagRecord[] };
  const flag = data.results.find((f) => f.key === ANNOUNCEMENTS_FLAG);
  if (!flag) {
    throw new Error(
      `Flag ${ANNOUNCEMENTS_FLAG} not found in project ${PROJECT_ID} — create it first.`,
    );
  }
  return flag;
}

export async function fetchCurrentUser(
  token: string,
): Promise<{ distinctId?: string; label?: string }> {
  const user = (await request(token, "/api/users/@me/")) as {
    distinct_id?: string | null;
    email?: string | null;
    first_name?: string | null;
    last_name?: string | null;
  };
  const name = [user.first_name, user.last_name].filter(Boolean).join(" ");
  return {
    distinctId: user.distinct_id ?? undefined,
    label: name || user.email || undefined,
  };
}

export function readPayload(flag: FlagRecord): unknown {
  const raw = flag.filters.payloads?.true;
  if (raw === undefined) return { announcements: [] };
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

/**
 * Writes only filters.payloads["true"], spreading the rest of `filters` —
 * PATCH replaces the filters object wholesale, and clobbering `groups` would
 * change the rollout. The release condition stays managed in the PostHog UI.
 */
export async function savePayload(
  token: string,
  flag: FlagRecord,
  payload: AnnouncementsPayload,
): Promise<FlagRecord> {
  const validated = announcementsPayloadSchema.parse(payload);
  return (await request(
    token,
    `/api/projects/${PROJECT_ID}/feature_flags/${flag.id}/`,
    {
      method: "PATCH",
      body: JSON.stringify({
        filters: {
          ...flag.filters,
          payloads: {
            ...(flag.filters.payloads ?? {}),
            true: JSON.stringify(validated),
          },
        },
      }),
    },
  )) as FlagRecord;
}
