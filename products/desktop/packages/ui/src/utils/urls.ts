import { type CloudRegion, getCloudUrlFromRegion } from "@posthog/shared";
import { useAuthStore } from "@posthog/ui/features/auth/store";

export function getPostHogUrl(
  pathOrUrl: string,
  regionOverride?: CloudRegion | null,
): string | null {
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  const region =
    regionOverride ?? useAuthStore.getState().authState.cloudRegion;
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
