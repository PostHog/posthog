import { basename } from "@posthog/core/message-editor/commands";

/**
 * How the composer shows the space context riding along with the prompt.
 *
 * A resolved context-wiki page is a session-wide mount, so it can be read but
 * not dropped from one task. The legacy CONTEXT.md is per-prompt text, so it
 * keeps its remove control.
 */
export function channelContextChipProps(channelContextPath?: string): {
  label: string;
  removable: boolean;
} {
  return channelContextPath
    ? { label: basename(channelContextPath), removable: false }
    : { label: "CONTEXT.md", removable: true };
}
