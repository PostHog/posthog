import { SquaresFourIcon } from "@phosphor-icons/react";
import {
  clampViewport,
  clampZoom,
  fitToContent,
  SKETCHPAD_FIT_MAX_ZOOM,
  sketchpadBounds,
  zoomAroundCenter,
  zoomTo,
} from "@posthog/core/sketchpad/sketchpadGeometry";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Skeleton,
} from "@posthog/quill";
import type { SketchpadFragment, SketchpadOp } from "@posthog/shared";
import {
  findFreeSpot,
  maxZ,
  minZ,
  SKETCHPAD_FRAGMENT_DEFAULT_HEIGHT,
  SKETCHPAD_FRAGMENT_DEFAULT_WIDTH,
} from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useCanvasViewedStore } from "@posthog/ui/features/canvas/stores/canvasViewedStore";
import { useApplySketchpadToolCalls } from "@posthog/ui/features/sketchpad/hooks/useApplySketchpadToolCalls";
import { useSketchpadApi } from "@posthog/ui/features/sketchpad/hooks/useSketchpadApi";
import { useSketchpadCache } from "@posthog/ui/features/sketchpad/hooks/useSketchpadCache";
import { useSketchpadKeyboard } from "@posthog/ui/features/sketchpad/hooks/useSketchpadKeyboard";
import {
  useSketchpadViewport,
  useSketchpadViewportStore,
} from "@posthog/ui/features/sketchpad/hooks/useSketchpadViewportStore";
import {
  SketchpadViewProvider,
  useSketchpadViewStore,
} from "@posthog/ui/features/sketchpad/interaction/sketchpadViewStore";
import { libraryEntry } from "@posthog/ui/features/sketchpad/library/registry";
import { usePresenceSender } from "@posthog/ui/features/sketchpad/presence/usePresenceSender";
import { useSketchpadPeers } from "@posthog/ui/features/sketchpad/presence/useSketchpadPeers";
import { useSketchpadStream } from "@posthog/ui/features/sketchpad/presence/useSketchpadStream";
import { useSketchpadSync } from "@posthog/ui/features/sketchpad/sync/useSketchpadSync";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { useQueryClient } from "@tanstack/react-query";
import {
  type ReactElement,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useShallow } from "zustand/react/shallow";
import { useSketchpadTaskId } from "../hooks/useSketchpadTaskLinkStore";
import { usePaneRect } from "../interaction/usePaneRect";
import { buildLastEdits } from "../lastEdits";
import { EditFragmentDialog } from "./EditFragmentDialog";
import type { FragmentLastEdit } from "./FragmentOverlay";
import { SketchpadEmptyHero } from "./SketchpadEmptyHero";
import { SketchpadHeader } from "./SketchpadHeader";
import { SketchpadMinimap } from "./SketchpadMinimap";
import { SketchpadSidePanel } from "./SketchpadSidePanel";
import { SketchpadStage } from "./SketchpadStage";
import { SketchpadToolbar } from "./SketchpadToolbar";

interface SketchpadViewProps {
  sketchpadId: string;
  channelId?: string;
}

export function SketchpadView(props: SketchpadViewProps): ReactElement {
  return (
    <SketchpadViewProvider key={props.sketchpadId}>
      <SketchpadScene {...props} />
    </SketchpadViewProvider>
  );
}

function SketchpadScene({
  sketchpadId,
  channelId,
}: {
  sketchpadId: string;
  channelId?: string;
}): ReactElement {
  const { paneRef, paneRect } = usePaneRect();
  const queryClient = useQueryClient();
  const api = useSketchpadApi();
  const authClient = useOptionalAuthenticatedClient();
  const currentUser = useCurrentUser({ client: authClient });
  const theme = useThemeStore((s) => (s.isDarkMode ? "dark" : "light"));
  const actorUser = useMemo(
    () =>
      currentUser.data
        ? {
            userId: currentUser.data.id,
            userName: currentUser.data.first_name || currentUser.data.email,
          }
        : undefined,
    [currentUser.data],
  );
  const { state, client } = useSketchpadSync(sketchpadId, api, actorUser);
  const getSnapshot = useCallback(() => client.getState().snapshot, [client]);

  useSketchpadCache(sketchpadId, state);

  const presence = usePresenceSender(sketchpadId);
  const { peers, ingest } = useSketchpadPeers(presence.clientId);
  useSketchpadStream(sketchpadId, {
    onOp: (entry) => client?.ingestStreamEntry(entry),
    onPresence: ingest,
    onReload: () => void client?.poll(),
    onLive: (live) => client?.setLive(live),
  });

  const viewport = useSketchpadViewport(sketchpadId);
  const setViewportForSketchpad = useSketchpadViewportStore(
    (s) => s.setViewport,
  );
  const fragments = state.snapshot.fragments;
  const setViewport = useCallback(
    (next: typeof viewport) => {
      const rect = paneRect;
      setViewportForSketchpad(
        sketchpadId,
        rect.width > 0 && rect.height > 0
          ? clampViewport(
              next,
              { w: rect.width, h: rect.height },
              sketchpadBounds(fragments),
            )
          : next,
      );
    },
    [sketchpadId, fragments, setViewportForSketchpad, paneRect],
  );
  const taskId = useSketchpadTaskId(sketchpadId);

  const view = useSketchpadViewStore(
    useShallow((state) => ({
      selectedIds: state.selectedIds,
      focusedId: state.focusedId,
      activePanel: state.activePanel,
      setSelection: state.setSelection,
      clearSelection: state.clearSelection,
      setActivePanel: state.setActivePanel,
      setHighlightedIds: state.setHighlightedIds,
    })),
  );
  const selectFragment = useCallback(
    (id: string) => view.setSelection([id]),
    [view.setSelection],
  );

  const openOnly = view.setActivePanel;
  const markCanvasViewed = useCanvasViewedStore(
    (viewed) => viewed.markCanvasViewed,
  );
  useEffect(() => {
    markCanvasViewed(sketchpadId, Date.now());
  }, [sketchpadId, markCanvasViewed]);
  const shareChannelId = channelId ?? state.channelId;
  const [editingId, setEditingId] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const applyLocal = useCallback(
    (ops: SketchpadOp[], opIds?: string[]) =>
      client?.applyLocal(ops, undefined, opIds),
    [client],
  );

  const addFromLibrary = useCallback(
    (name: string, world?: { x: number; y: number }) => {
      const entry = libraryEntry(name);
      if (!entry || !client) return;
      const snapshot = client.getState().snapshot;
      const size = entry.defaultSize ?? {
        w: SKETCHPAD_FRAGMENT_DEFAULT_WIDTH,
        h: SKETCHPAD_FRAGMENT_DEFAULT_HEIGHT,
      };
      const spot = world ?? findFreeSpot(snapshot, size.w, size.h);
      const fragment: SketchpadFragment = {
        id: `${entry.name}-${globalThis.crypto.randomUUID()}`,
        title: entry.label,
        x: Math.round(spot.x),
        y: Math.round(spot.y),
        w: size.w,
        h: size.h,
        z: entry.layer === "back" ? minZ(snapshot) - 1 : maxZ(snapshot) + 1,
        code: entry.code,
        codeVersion: 1,
        surface: entry.surface ?? "card",
        hidden: false,
      };
      client.applyLocal([{ type: "add_fragment", fragment }]);
      view.setSelection([fragment.id]);
    },
    [client, view],
  );

  useApplySketchpadToolCalls(client, taskId, selectFragment);

  useSketchpadKeyboard({
    enabled: editingId === null && view.focusedId === null,
    paneRect,
    fragments: state.snapshot.fragments,
    viewport,
    setViewport,
    selectedIds: view.selectedIds,
    onDeleteSelected: (ids) => {
      applyLocal(ids.map((id) => ({ type: "remove_fragment", id })));
      view.clearSelection();
    },
    onClearSelection: () => view.clearSelection(),
    onSelectAll: () =>
      view.setSelection(state.snapshot.fragments.map((f) => f.id)),
    onUndo: () => void client?.undoLastOwnOp(),
  });

  useEffect(() => {
    presence.reportSelection(view.selectedIds);
  }, [presence, view.selectedIds]);

  useEffect(() => {
    presence.reportViewport(viewport);
  }, [presence, viewport]);

  const lastEdits: Record<string, FragmentLastEdit> = useMemo(
    () => buildLastEdits(state.log),
    [state.log],
  );

  const editingFragment =
    state.snapshot.fragments.find((f) => f.id === editingId) ?? null;

  const initialLoading =
    state.status === "loading" &&
    !currentUser.isError &&
    state.log.length === 0 &&
    state.snapshot.fragments.length === 0;
  const initialError =
    currentUser.isError || (state.status === "error" && state.headSeq === 0);

  if (initialLoading) {
    return (
      <div className="flex h-full flex-col gap-4 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-full w-full" />
      </div>
    );
  }

  if (initialError) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <SquaresFourIcon />
          </EmptyMedia>
          <EmptyTitle>Could not load this board</EmptyTitle>
          <EmptyDescription>
            The board may be deleted, or the connection failed. Go back and try
            again.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  const fitSketchpad = (): void => {
    const rect = paneRect;
    if (rect.width > 0 && rect.height > 0)
      setViewport(fitToContent(state.snapshot.fragments, rect));
  };
  const zoomStep = (factor: number): void => {
    const rect = paneRect;
    setViewport(
      rect.width > 0 && rect.height > 0
        ? zoomAroundCenter(viewport, factor, rect)
        : { ...viewport, zoom: clampZoom(viewport.zoom * factor) },
    );
  };
  const resetZoom = (): void => {
    const rect = paneRect;
    setViewport(
      rect.width > 0 && rect.height > 0
        ? zoomTo(viewport, 1, rect)
        : { ...viewport, zoom: SKETCHPAD_FIT_MAX_ZOOM },
    );
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <SketchpadHeader
        sketchpadId={sketchpadId}
        channelId={channelId}
        shareChannelId={shareChannelId}
        name={state.name}
        onNameChange={(name) => client.setName(name)}
        peers={peers}
        status={state.status}
      />

      <div className="flex min-h-0 flex-1">
        <div className="relative flex min-w-0 flex-1 flex-col">
          {view.focusedId ? null : (
            <SketchpadToolbar
              zoom={viewport.zoom}
              activePanel={view.activePanel}
              onZoomIn={() => zoomStep(1.2)}
              onZoomOut={() => zoomStep(1 / 1.2)}
              onZoomReset={resetZoom}
              onFitToContent={fitSketchpad}
              onPanelChange={openOnly}
            />
          )}
          <div className="relative min-h-0 flex-1">
            <SketchpadStage
              sketchpadId={sketchpadId}
              paneRef={paneRef}
              paneRect={paneRect}
              snapshot={state.snapshot}
              getSnapshot={getSnapshot}
              viewport={viewport}
              setViewport={setViewport}
              applyLocal={applyLocal}
              theme={theme}
              queryClient={queryClient}
              fragmentErrors={state.fragmentErrors}
              onFragmentError={(id, message) =>
                client?.setFragmentError(id, message)
              }
              lastEdits={lastEdits}
              onEditFragment={setEditingId}
              dragActive={dragActive}
              onDropFragment={(name, world) => addFromLibrary(name, world)}
              peers={peers}
              onCursor={presence.reportCursor}
              onCaret={presence.reportCaret}
            />
            <SketchpadMinimap
              fragments={view.focusedId ? [] : state.snapshot.fragments}
              viewport={viewport}
              paneRect={paneRect}
              selectedIds={view.selectedIds}
              onJump={(world) => {
                const rect = paneRect;
                if (rect.width === 0 || rect.height === 0) return;
                setViewport({
                  zoom: viewport.zoom,
                  x: rect.width / 2 - world.x * viewport.zoom,
                  y: rect.height / 2 - world.y * viewport.zoom,
                });
              }}
            />
            {state.snapshot.fragments.length === 0 && !view.focusedId ? (
              <SketchpadEmptyHero
                sketchpadId={sketchpadId}
                sketchpadName={state.name}
                snapshot={state.snapshot}
                headSeq={state.headSeq}
                onStarted={() => openOnly("chat")}
                onAddFragment={(name) => addFromLibrary(name)}
                onOpenLibrary={() => openOnly("palette")}
              />
            ) : null}
          </div>
        </div>

        <SketchpadSidePanel
          activePanel={view.activePanel}
          onClose={() => openOnly(null)}
          state={state}
          sketchpadId={sketchpadId}
          taskId={taskId}
          currentUserId={actorUser?.userId}
          onAddFragment={addFromLibrary}
          onDragStateChange={setDragActive}
          onRestore={(seq) => client.restoreTo(seq)}
          onHighlight={view.setHighlightedIds}
          onLoadFullLog={() => void client.loadFullLog()}
          onRebasePending={() => client.rebasePendingAfterCompaction()}
          onDiscardPending={() => client.discardPendingAfterCompaction()}
        />
      </div>

      <EditFragmentDialog
        open={editingId !== null}
        fragment={editingFragment}
        onOpenChange={(open) => setEditingId(open ? editingId : null)}
        applyLocal={applyLocal}
      />
    </div>
  );
}
