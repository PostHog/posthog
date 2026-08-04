import { isSafeExternalUrl } from "@posthog/shared";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";

export async function openUrlInBrowser(url: string): Promise<void> {
  if (!isSafeExternalUrl(url)) return;
  try {
    openExternalUrl(url);
  } catch {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}
