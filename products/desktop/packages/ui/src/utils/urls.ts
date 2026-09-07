import { resolveServiceOptional } from "@posthog/di/container";
import {
  PREVIEW_DEPLOYMENT,
  type PreviewDeploymentInfo,
} from "@posthog/platform/preview-deployment";
import { type CloudRegion, getCloudUrlFromRegion } from "@posthog/shared";
import { useAuthStore } from "@posthog/ui/features/auth/store";

/**
 * The origin this build's copied-browser links must target. A preview build
 * resolves it from the bound preview deployment; ordinary builds return null
 * (the region path applies). Called from event handlers outside React, so the
 * port is read from the root container rather than a hook.
 */
function getPreviewOrigin(): string | null {
  const preview = resolveServiceOptional<PreviewDeploymentInfo | null>(
    PREVIEW_DEPLOYMENT,
  );
  return preview ? preview.manifest.backendOrigin : null;
}

export function getPostHogUrl(
  pathOrUrl: string,
  regionOverride?: CloudRegion | null,
): string | null {
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  const authState = useAuthStore.getState().authState;
  // A preview session has no ordinary region: every copied-browser-link base
  // must be the preview origin, never the region placeholder.
  if (authState.deploymentTarget === "preview") {
    const preview = getPreviewOrigin();
    if (!preview) return null;
    return `${preview}${pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`}`;
  }
  const region = regionOverride ?? authState.cloudRegion;
  if (!region) return null;
  const base = getCloudUrlFromRegion(region);
  return `${base}${pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`}`;
}

export function getBillingUrl(
  regionOverride?: CloudRegion | null,
): string | null {
  return getPostHogUrl(
    "/organization/billing/overview?products=posthog_code_usage",
    regionOverride,
  );
}
