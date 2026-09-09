import { ArrowLeftIcon, LinkIcon } from "@phosphor-icons/react";
import type { PresencePeer } from "@posthog/core/sketchpad/sketchpadPresence";
import type { SketchpadSyncStatus } from "@posthog/core/sketchpad/sketchpadSync";
import { Button } from "@posthog/quill";
import { copyCanvasUrl } from "@posthog/ui/features/canvas/utils/copyCanvasLink";
import { HeaderTitleEditor } from "@posthog/ui/features/task-detail/HeaderTitleEditor";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToCanvases,
  navigateToSpaceCanvases,
} from "@posthog/ui/router/navigationBridge";
import { sketchpadShareUrl } from "@posthog/ui/utils/posthogLinks";
import { type ReactElement, useState } from "react";
import { useSketchpadMutations } from "../hooks/useSketchpadMutations";
import {
  COPY_SKETCHPAD_LINK_ACTION,
  DEFAULT_SKETCHPAD_NAME,
} from "../sketchpadCopy";
import { PresenceFaces } from "./PresenceFaces";
import { SyncChip } from "./SyncChip";

interface SketchpadHeaderProps {
  sketchpadId: string;
  channelId?: string;
  shareChannelId: string | null;
  name: string;
  onNameChange: (name: string) => void;
  peers: readonly PresencePeer[];
  status: SketchpadSyncStatus;
}

export function SketchpadHeader({
  sketchpadId,
  channelId,
  shareChannelId,
  name,
  onNameChange,
  peers,
  status,
}: SketchpadHeaderProps): ReactElement {
  const [renaming, setRenaming] = useState(false);
  const { renameSketchpad, isRenaming } = useSketchpadMutations();
  return (
    <header className="flex h-12 shrink-0 items-center gap-2.5 border-(--gray-4) border-b px-3">
      <Button
        variant="default"
        size="icon-sm"
        aria-label="Back to canvases"
        onClick={() =>
          channelId ? navigateToSpaceCanvases(channelId) : navigateToCanvases()
        }
      >
        <ArrowLeftIcon />
      </Button>
      <h1 className="flex min-w-0 flex-1">
        {renaming ? (
          <HeaderTitleEditor
            initialTitle={name}
            onSubmit={(next) => {
              setRenaming(false);
              onNameChange(next);
              void renameSketchpad(sketchpadId, next).catch(
                (error: unknown) => {
                  onNameChange(name);
                  toast.error(
                    error instanceof Error ? error.message : String(error),
                  );
                },
              );
            }}
            onCancel={() => setRenaming(false)}
            className="h-7 min-w-0 flex-1 px-1.5 font-semibold text-[15px] tracking-tight"
          />
        ) : (
          <button
            type="button"
            title="Rename…"
            disabled={isRenaming}
            className="min-w-0 truncate rounded-(--radius-2) px-1.5 py-0.5 text-left font-semibold text-[15px] tracking-tight transition-colors hover:bg-(--gray-3)"
            onClick={() => setRenaming(true)}
          >
            {name || DEFAULT_SKETCHPAD_NAME}
          </button>
        )}
      </h1>
      <div className="ml-auto flex shrink-0 items-center gap-2.5">
        <Button
          variant="default"
          size="icon-sm"
          aria-label={COPY_SKETCHPAD_LINK_ACTION}
          title={COPY_SKETCHPAD_LINK_ACTION}
          disabled={!shareChannelId}
          onClick={() => {
            if (shareChannelId) {
              void copyCanvasUrl(
                sketchpadShareUrl(shareChannelId, sketchpadId),
                shareChannelId,
                sketchpadId,
                "canvas",
              );
            }
          }}
        >
          <LinkIcon />
        </Button>
        <PresenceFaces peers={peers} />
        <SyncChip status={status} />
      </div>
    </header>
  );
}
