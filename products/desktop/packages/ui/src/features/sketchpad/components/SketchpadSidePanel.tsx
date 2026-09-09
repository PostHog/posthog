import type { SketchpadSyncState } from "@posthog/core/sketchpad/sketchpadSync";
import type { ReactElement } from "react";
import type { SketchpadPanelName } from "../interaction/sketchpadViewStore";
import { HistoryPanel } from "./HistoryPanel";
import { LibraryPalette } from "./LibraryPalette";
import { SketchpadChatPanel } from "./SketchpadChatPanel";
import { StateInspector } from "./StateInspector";

interface SketchpadSidePanelProps {
  activePanel: SketchpadPanelName | null;
  onClose: () => void;
  state: SketchpadSyncState;
  sketchpadId: string;
  taskId?: string;
  currentUserId?: number;
  onAddFragment: (name: string) => void;
  onDragStateChange: (active: boolean) => void;
  onRestore: (seq: number) => void;
  onHighlight: (ids: string[]) => void;
  onLoadFullLog: () => void;
  onRebasePending: () => void;
  onDiscardPending: () => void;
}

export function SketchpadSidePanel(
  props: SketchpadSidePanelProps,
): ReactElement | null {
  if (props.activePanel === null) return null;
  return (
    <div className="flex w-96 shrink-0 flex-col overflow-hidden">
      <PanelContent {...props} activePanel={props.activePanel} />
    </div>
  );
}

function PanelContent({
  activePanel,
  onClose,
  state,
  sketchpadId,
  taskId,
  currentUserId,
  onAddFragment,
  onDragStateChange,
  onRestore,
  onHighlight,
  onLoadFullLog,
  onRebasePending,
  onDiscardPending,
}: SketchpadSidePanelProps & {
  activePanel: SketchpadPanelName;
}): ReactElement {
  switch (activePanel) {
    case "palette":
      return (
        <LibraryPalette
          onAdd={(entry) => onAddFragment(entry.name)}
          onDragStateChange={onDragStateChange}
          onClose={onClose}
        />
      );
    case "history":
      return (
        <HistoryPanel
          state={state}
          onRestore={onRestore}
          onHighlight={onHighlight}
          onLoadFullLog={onLoadFullLog}
          onRebasePending={onRebasePending}
          onDiscardPending={onDiscardPending}
          currentUserId={currentUserId}
          onClose={onClose}
        />
      );
    case "inspector":
      return (
        <StateInspector
          state={state.snapshot.state}
          fragments={state.snapshot.fragments}
          onClose={onClose}
        />
      );
    case "chat":
      return (
        <SketchpadChatPanel
          sketchpadId={sketchpadId}
          sketchpadName={state.name}
          snapshot={state.snapshot}
          headSeq={state.headSeq}
          taskId={taskId}
          onClose={onClose}
        />
      );
  }
}
