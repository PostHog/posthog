import { resolveServiceOptional } from "@posthog/di/container";
import {
  DISK_CACHE_IMAGES,
  type IDiskCacheImages,
} from "@posthog/platform/disk-cache";

export function cachedImageUrl(remoteUrl: string): string {
  return (
    resolveServiceOptional<IDiskCacheImages>(DISK_CACHE_IMAGES)?.imageUrl(
      remoteUrl,
    ) ?? remoteUrl
  );
}
