import {
  type CloudRegion,
  getCloudUrlFromRegion,
  REGION_LABELS,
} from "@posthog/shared";
import { useAuthStore } from "@posthog/ui/features/auth/store";
import { getPostHogUrl } from "@posthog/ui/utils/urls";

export interface LinkOverrides {
  projectId?: number | null;
  cloudRegion?: CloudRegion | null;
}

export interface ErrorTrackingIssueLinkOverrides extends LinkOverrides {
  fingerprint?: string | null;
}

function resolveProjectId(override?: number | null): number | null {
  if (override != null) return override;
  return useAuthStore.getState().authState.currentProjectId ?? null;
}

function withProjectId(
  path: (projectId: number) => string,
  overrides?: LinkOverrides,
): string | null {
  const projectId = resolveProjectId(overrides?.projectId);
  if (!projectId) return null;
  return getPostHogUrl(path(projectId), overrides?.cloudRegion);
}

export function flagUrl(
  flagId: number,
  overrides?: LinkOverrides,
): string | null {
  return withProjectId(
    (pid) => `/project/${pid}/feature_flags/${flagId}`,
    overrides,
  );
}

export function flagUrlByKey(
  flagKey: string,
  overrides?: LinkOverrides,
): string | null {
  return withProjectId(
    (pid) =>
      `/project/${pid}/feature_flags?search=${encodeURIComponent(flagKey)}`,
    overrides,
  );
}

export function eventDefinitionUrl(
  definitionId: string,
  overrides?: LinkOverrides,
): string | null {
  return withProjectId(
    (pid) => `/project/${pid}/data-management/events/${definitionId}`,
    overrides,
  );
}

export function experimentUrl(
  experimentId: number,
  overrides?: LinkOverrides,
): string | null {
  return withProjectId(
    (pid) => `/project/${pid}/experiments/${experimentId}`,
    overrides,
  );
}

export function skillUrl(
  skillName: string,
  overrides?: LinkOverrides,
): string | null {
  return withProjectId(
    (pid) => `/project/${pid}/skills/${encodeURIComponent(skillName)}`,
    overrides,
  );
}

/** The browser-accessible URL for a Self-driving report. */
export function inboxReportUrl(
  reportId: string,
  overrides?: LinkOverrides,
): string | null {
  return withProjectId(
    (pid) => `/project/${pid}/inbox/${encodeURIComponent(reportId)}`,
    overrides,
  );
}

/**
 * The shareable https link for a canvas (a dashboard inside a channel):
 * `<instance>/desktop/canvas/<channelId>/<dashboardId>`. Opening it in a browser
 * hits a web interstitial that deep-links into the desktop app (or offers the
 * download), so the link works for anyone — app installed or not. Not
 * project-scoped: the ids are globally-unique desktop file-system row ids. The
 * inbound desktop side lives in `CanvasLinkService` / `useCanvasDeepLink`.
 */
export function canvasShareUrl(
  channelId: string,
  dashboardId: string,
  regionOverride?: CloudRegion | null,
): string | null {
  return getPostHogUrl(
    `/desktop/canvas/${encodeURIComponent(channelId)}/${encodeURIComponent(dashboardId)}`,
    regionOverride,
  );
}

/**
 * The shareable https link for a channel — or a thread (channel-filed task)
 * inside it: `<instance>/desktop/channel/<channelId>[/tasks/<taskId>]`. Opening
 * it in a browser hits a web interstitial that deep-links into the desktop app
 * (or offers the download), so the link works for anyone — app installed or
 * not. Not project-scoped: the ids are globally-unique row ids. The inbound
 * desktop side lives in `ChannelLinkService` / `useChannelDeepLink`.
 */
export function channelShareUrl(
  channelId: string,
  taskId?: string,
): string | null {
  const base = `/desktop/channel/${encodeURIComponent(channelId)}`;
  return getPostHogUrl(
    taskId ? `${base}/tasks/${encodeURIComponent(taskId)}` : base,
  );
}

/**
 * The "open a copy" form of a canvas link. It is the same https bridge with a
 * `fork` flag: the app opening it copies the canvas into the opener's own space
 * and shows the copy, leaving the original untouched.
 */
export function canvasForkUrl(
  channelId: string,
  dashboardId: string,
  regionOverride?: CloudRegion | null,
): string | null {
  const base = canvasShareUrl(channelId, dashboardId, regionOverride);
  return base ? `${base}?fork=1` : null;
}

/** The public page for a sharing configuration's access token. */
export function sharedResourceUrl(
  accessToken: string,
  regionOverride?: CloudRegion | null,
): string | null {
  return getPostHogUrl(
    `/shared/${encodeURIComponent(accessToken)}`,
    regionOverride,
  );
}

/** The comment scope a task-run artifact is addressed under. */
export const ARTIFACT_LINK_SCOPE = "task_artifact";

/**
 * The shareable https link for a task-run artifact:
 * `<instance>/desktop/task/<taskId>?scope=task_artifact&item=<artifactId>`. It
 * rides the task bridge: the web interstitial forwards `scope` and `item` onto
 * the desktop scheme, and the app opens the artifact's tab once the task shows.
 * The artifact id is any version's manifest id; the app resolves it to the
 * file's name and run. The inbound side lives in `TaskLinkService` /
 * `useOpenRequestedArtifact`.
 */
export function artifactShareUrl(
  taskId: string,
  artifactId: string,
  regionOverride?: CloudRegion | null,
): string | null {
  const params = new URLSearchParams({
    scope: ARTIFACT_LINK_SCOPE,
    item: artifactId,
  });
  return getPostHogUrl(
    `/desktop/task/${encodeURIComponent(taskId)}?${params.toString()}`,
    regionOverride,
  );
}

/**
 * Parse a URL, rejecting anything that isn't https. The gate every surface that
 * renders a backend-supplied link goes through before fetching from it or
 * handing it to the host's external-link opener.
 */
export function parseHttpsUrl(url: string): URL | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" ? parsed : null;
  } catch {
    return null;
  }
}

export type ShareLinkTarget =
  | { kind: "canvas"; channelId: string; dashboardId: string; fork?: boolean }
  | { kind: "channel"; channelId: string; taskId?: string }
  | { kind: "artifact"; taskId: string; artifactId: string };

const POSTHOG_HOSTS = new Set(
  (Object.keys(REGION_LABELS) as CloudRegion[])
    .map((region) => {
      try {
        return new URL(getCloudUrlFromRegion(region)).host;
      } catch {
        return "";
      }
    })
    .filter(Boolean),
);

interface ShareLinkRoute {
  pattern: string[];
  /** Returns null when the query does not carry what the route needs. */
  build: (
    params: Record<string, string>,
    query: URLSearchParams,
  ) => ShareLinkTarget | null;
}

// The bridges live under /desktop. "code" is their pre-rename prefix, still in
// messages and clipboards, so both shapes open in the app.
const BRIDGE_PREFIXES = ["desktop", "code"];

const BRIDGE_ROUTES: ShareLinkRoute[] = [
  {
    pattern: ["canvas", ":channelId", ":dashboardId"],
    build: ({ channelId, dashboardId }, query) => ({
      kind: "canvas",
      channelId,
      dashboardId,
      ...(query.get("fork") === "1" ? { fork: true } : {}),
    }),
  },
  {
    pattern: ["channel", ":channelId"],
    build: ({ channelId }) => ({ kind: "channel", channelId }),
  },
  {
    pattern: ["channel", ":channelId", "tasks", ":taskId"],
    build: ({ channelId, taskId }) => ({ kind: "channel", channelId, taskId }),
  },
  // Only an artifact-addressed task link is a share target. A bare task link
  // (or one focusing a comment) stays a browser link, as it always has.
  {
    pattern: ["task", ":taskId"],
    build: ({ taskId }, query) => {
      const artifactId = query.get("item");
      if (
        query.has("comment") ||
        query.get("scope") !== ARTIFACT_LINK_SCOPE ||
        !artifactId
      ) {
        return null;
      }
      return { kind: "artifact", taskId, artifactId };
    },
  },
];

const SHARE_LINK_ROUTES: ShareLinkRoute[] = BRIDGE_PREFIXES.flatMap((prefix) =>
  BRIDGE_ROUTES.map((route) => ({
    ...route,
    pattern: [prefix, ...route.pattern],
  })),
);

function decodePathSegments(pathname: string): string[] {
  return pathname
    .split("/")
    .filter(Boolean)
    .map((segment) => {
      try {
        return decodeURIComponent(segment);
      } catch {
        return segment;
      }
    });
}

function matchRoute(
  segments: string[],
  query: URLSearchParams,
  route: ShareLinkRoute,
): ShareLinkTarget | null {
  if (segments.length !== route.pattern.length) return null;
  const params: Record<string, string> = {};
  for (const [index, token] of route.pattern.entries()) {
    const segment = segments[index];
    if (token.startsWith(":")) {
      params[token.slice(1)] = segment;
    } else if (token !== segment) {
      return null;
    }
  }
  return route.build(params, query);
}

export function parseShareLink(href: string): ShareLinkTarget | null {
  let url: URL;
  try {
    url = new URL(href);
  } catch {
    return null;
  }
  if (!POSTHOG_HOSTS.has(url.host)) return null;

  const segments = decodePathSegments(url.pathname);
  for (const route of SHARE_LINK_ROUTES) {
    const target = matchRoute(segments, url.searchParams, route);
    if (target) return target;
  }
  return null;
}

export function errorTrackingIssueUrl(
  issueId: string,
  overrides?: ErrorTrackingIssueLinkOverrides,
): string | null {
  return withProjectId((pid) => {
    const path = `/project/${pid}/error_tracking/${encodeURIComponent(issueId)}`;
    return overrides?.fingerprint
      ? `${path}?fingerprint=${encodeURIComponent(overrides.fingerprint)}`
      : path;
  }, overrides);
}
