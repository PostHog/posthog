import { Label, Switch, Text } from "@posthog/quill";
import { type ReactNode, useId } from "react";
import { LinkCopyRow } from "./LinkCopyRow";
import { ShareSection } from "./ShareSection";

export interface PublicShareState {
  enabled: boolean;
  accessToken: string | null;
}

/**
 * The "Public link" section: a heading with the on/off switch, one line on what
 * the link shows, and the link itself while sharing is on. Renders nothing when
 * `sharing` is null: that is the service saying the backend has no sharing
 * route for this kind of thing yet, and a section that cannot work is worse
 * than no section.
 */
export function PublicShareSection({
  sharing,
  isLoading,
  isError,
  isPending,
  onToggle,
  publicUrl,
  description,
  disabledReason,
  dataAttrPrefix,
  children,
}: {
  sharing: PublicShareState | null | undefined;
  isLoading: boolean;
  isError: boolean;
  /** A toggle request is in flight; the switch waits for it. */
  isPending: boolean;
  onToggle: (enabled: boolean) => void;
  publicUrl: string | null;
  /** One line on what the public link shows, for the current on/off state. */
  description: string;
  /** Why sharing cannot be turned on right now; shown in place of the description. */
  disabledReason?: string;
  dataAttrPrefix: string;
  /** Extra rows that only apply while sharing is on. */
  children?: ReactNode;
}) {
  const switchId = useId();

  if (isLoading) {
    return (
      <Text size="xs" variant="muted">
        Loading public sharing…
      </Text>
    );
  }
  if (isError) {
    return (
      <Text size="xs" variant="muted" role="alert">
        Couldn't load public sharing. Close this dialog and try again.
      </Text>
    );
  }
  if (!sharing) return null;

  return (
    <ShareSection
      title={<Label htmlFor={switchId}>Public link</Label>}
      control={
        <Switch
          id={switchId}
          checked={sharing.enabled}
          disabled={isPending || disabledReason !== undefined}
          onCheckedChange={(checked) => onToggle(checked)}
          data-attr={`${dataAttrPrefix}-public-toggle`}
        />
      }
      description={disabledReason ?? description}
    >
      {sharing.enabled ? (
        <>
          <LinkCopyRow
            label="Public link"
            hideLabel
            url={publicUrl}
            copiedDescription="Anyone with the link can view."
            dataAttr={`${dataAttrPrefix}-copy-public-link`}
          />
          {children}
        </>
      ) : null}
    </ShareSection>
  );
}
