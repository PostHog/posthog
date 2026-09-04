import { Label, Switch, Text } from "@posthog/quill";
import { type ReactNode, useId } from "react";
import { LinkCopyRow } from "./LinkCopyRow";

export interface PublicShareState {
  enabled: boolean;
  accessToken: string | null;
}

/**
 * The "anyone with the link" toggle. Renders nothing when `sharing` is null:
 * that is the service saying the backend has no sharing route for this kind of
 * thing yet, and a section that cannot work is worse than no section.
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
  description: string;
  /** Why sharing cannot be turned on right now; shown in place of the description. */
  disabledReason?: string;
  dataAttrPrefix: string;
  /** Extra controls that only apply while sharing is on. */
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
    <div className="flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <Switch
          id={switchId}
          checked={sharing.enabled}
          disabled={isPending || disabledReason !== undefined}
          onCheckedChange={(checked) => onToggle(checked)}
          data-attr={`${dataAttrPrefix}-public-toggle`}
        />
        <div className="flex min-w-0 flex-col gap-0.5">
          <Label htmlFor={switchId}>Share publicly</Label>
          <Text size="xs" variant="muted">
            {disabledReason ?? description}
          </Text>
        </div>
      </div>
      {sharing.enabled ? (
        <>
          <LinkCopyRow
            label="Public link"
            url={publicUrl}
            copiedDescription="Anyone with the link can view."
            dataAttr={`${dataAttrPrefix}-copy-public-link`}
          />
          {children}
        </>
      ) : null}
    </div>
  );
}
