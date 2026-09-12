import { toast } from "@posthog/ui/primitives/toast";

/** Copy a share link, toasting what the link does on success and the failure otherwise. */
export async function copyLinkToClipboard(
  url: string,
  copiedDescription: string,
  onCopied?: (success: boolean) => void,
): Promise<void> {
  try {
    await navigator.clipboard.writeText(url);
    toast.success("Link copied", { description: copiedDescription });
    onCopied?.(true);
  } catch (error) {
    toast.error("Couldn't copy link", {
      description: error instanceof Error ? error.message : String(error),
    });
    onCopied?.(false);
  }
}
