import type { PreviewDeploymentInfo } from "@posthog/platform/preview-deployment";
import type { FeatureFlags } from "@posthog/ui/features/feature-flags/identifiers";

/**
 * Layer a preview deployment's declared flag overrides over a host's feature
 * flags. Overrides apply before the first `isEnabled` read and survive flag
 * refreshes, because the decorator answers from the manifest every time. A
 * `false` override stays false — the point is to test the flag-off app
 * against a preview backend, not to force everything on.
 *
 * Only the desktop preview host constructs this with a non-null preview;
 * ordinary builds pass null and get the wrapped flags back unchanged.
 */
export function bindPreviewFeatureFlags(
  flags: FeatureFlags,
  preview: PreviewDeploymentInfo | null,
): FeatureFlags {
  if (!preview) {
    return flags;
  }
  const overrides = preview.manifest.featureFlags;
  return {
    isEnabled: (flagKey) =>
      flagKey in overrides ? overrides[flagKey] : flags.isEnabled(flagKey),
    getPayload: (flagKey) => flags.getPayload(flagKey),
    getVariant: (flagKey) => flags.getVariant(flagKey),
    onFlagsLoaded: (handler) => flags.onFlagsLoaded(handler),
  };
}
