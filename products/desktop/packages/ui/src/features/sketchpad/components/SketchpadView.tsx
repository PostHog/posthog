import {
  ArrowLeftIcon,
  LinkIcon,
  SquaresFourIcon,
} from "@phosphor-icons/react";
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
  Button,
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
import { copyCanvasLink } from "@posthog/ui/features/canvas/utils/copyCanvasLink";
import { useApplySketchpadToolCalls } from "@posthog/ui/features/sketchpad/hooks/useApplySketchpadToolCalls";
import { useSketchpadApi } from "@posthog/ui/features/sketchpad/hooks/useSketchpadApi";
import { useSketchpadCache } from "@posthog/ui/features/sketchpad/hooks/useSketchpadCache";
import { useSketchpadKeyboard } from "@posthog/ui/features/sketchpad/hooks/useSketchpadKeyboard";
import { useSketchpadMutations } from "@posthog/ui/features/sketchpad/hooks/useSketchpadMutations";
import {
  useSketchpadTaskId,
  useSketchpadViewport,
  useSketchpadViewportStore,
} from "@posthog/ui/features/sketchpad/hooks/useSketchpadViewportStore";
import {
  selectSketchpadFragment,
  useSketchpadViewStore,
} from "@posthog/ui/features/sketchpad/interaction/sketchpadViewStore";
import { libraryEntry } from "@posthog/ui/features/sketchpad/library/registry";
import { usePresenceSender } from "@posthog/ui/features/sketchpad/presence/usePresenceSender";
import { useSketchpadPeers } from "@posthog/ui/features/sketchpad/presence/useSketchpadPeers";
import { useSketchpadStream } from "@posthog/ui/features/sketchpad/presence/useSketchpadStream";
import {
  COPY_SKETCHPAD_LINK_ACTION,
  DEFAULT_SKETCHPAD_NAME,
} from "@posthog/ui/features/sketchpad/sketchpadCopy";
import { useSketchpadSync } from "@posthog/ui/features/sketchpad/sync/useSketchpadSync";
import { HeaderTitleEditor } from "@posthog/ui/features/task-detail/HeaderTitleEditor";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToCanvases,
  navigateToSpaceCanvases,
} from "@posthog/ui/router/navigationBridge";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { useQueryClient } from "@tanstack/react-query";
import {
  type ReactElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { readPaneRect } from "../interaction/useSketchpadPointer";
import { buildLastEdits } from "../lastEdits";
import { EditFragmentDialog } from "./EditFragmentDialog";
import type { FragmentLastEdit } from "./FragmentOverlay";
import { HistoryPanel } from "./HistoryPanel";
import { LibraryPalette } from "./LibraryPalette";
import { PresenceFaces } from "./PresenceFaces";
import { SketchpadChatPanel } from "./SketchpadChatPanel";
import { SketchpadEmptyHero } from "./SketchpadEmptyHero";
import { SketchpadMinimap } from "./SketchpadMinimap";
import { SketchpadStage } from "./SketchpadStage";
import { SketchpadToolbar } from "./SketchpadToolbar";
import { StateInspector } from "./StateInspector";
import { SyncChip } from "./SyncChip";

const EMPTY_PANE = { left: 0, top: 0, width: 0, height: 0 };

export function SketchpadView({
  sketchpadId,
  channelId,
}: {
  sketchpadId: string;
  channelId?: string;
}): ReactElement {
  const paneRef = useRef<HTMLDivElement | null>(null);
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
      const rect = readPaneRect(paneRef.current);
      setViewportForSketchpad(
        sketchpadId,
        rect
          ? clampViewport(
              next,
              { w: rect.width, h: rect.height },
              sketchpadBounds(fragments),
            )
          : next,
      );
    },
    [sketchpadId, fragments, setViewportForSketchpad],
  );
  const taskId = useSketchpadTaskId(sketchpadId);

  const view = useSketchpadViewStore();
  const openOnly = view.setActivePanel;
  const markCanvasViewed = useCanvasViewedStore(
    (viewed) => viewed.markCanvasViewed,
  );
  useEffect(() => {
    markCanvasViewed(sketchpadId, Date.now());
  }, [sketchpadId, markCanvasViewed]);
  const shareChannelId = channelId ?? state.channelId;
  const [renaming, setRenaming] = useState(false);
  const { renameSketchpad, isRenaming } = useSketchpadMutations();
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
        ...(entry.surface ? { surface: entry.surface } : {}),
      };
      client.applyLocal([{ type: "add_fragment", fragment }]);
      view.setSelection([fragment.id]);
    },
    [client, view],
  );

  useApplySketchpadToolCalls(client, taskId, selectSketchpadFragment);

  useSketchpadKeyboard({
    enabled: editingId === null && view.focusedId === null,
    paneRef,
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

  if (
    state.status === "loading" &&
    !currentUser.isError &&
    state.log.length === 0 &&
    state.snapshot.fragments.length === 0
  ) {
    return (
      <div className="flex h-full flex-col gap-4 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-full w-full" />
      </div>
    );
  }

  if (
    currentUser.isError ||
    (state.status === "error" && state.headSeq === 0)
  ) {
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
    const rect = readPaneRect(paneRef.current);
    if (rect) setViewport(fitToContent(state.snapshot.fragments, rect));
  };
  const zoomStep = (factor: number): void => {
    const rect = readPaneRect(paneRef.current);
    setViewport(
      rect
        ? zoomAroundCenter(viewport, factor, rect)
        : { ...viewport, zoom: clampZoom(viewport.zoom * factor) },
    );
  };
  const resetZoom = (): void => {
    const rect = readPaneRect(paneRef.current);
    setViewport(
      rect
        ? zoomTo(viewport, 1, rect)
        : { ...viewport, zoom: SKETCHPAD_FIT_MAX_ZOOM },
    );
  };

  const panelOpen = view.activePanel !== null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2.5 border-(--gray-4) border-b px-3">
        <Button
          variant="default"
          size="icon-sm"
          aria-label="Back to canvases"
          onClick={() =>
            channelId
              ? navigateToSpaceCanvases(channelId)
              : navigateToCanvases()
          }
        >
          <ArrowLeftIcon />
        </Button>
        <h1 className="flex min-w-0 flex-1">
          {renaming ? (
            <HeaderTitleEditor
              initialTitle={state.name}
              onSubmit={(next) => {
                setRenaming(false);
                client?.setName(next);
                void renameSketchpad(sketchpadId, next).catch(
                  (error: unknown) => {
                    client?.setName(state.name);
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
              {state.name || DEFAULT_SKETCHPAD_NAME}
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
                void copyCanvasLink(
                  shareChannelId,
                  sketchpadId,
                  "canvas",
                  "sketchpad",
                );
              }
            }}
          >
            <LinkIcon />
          </Button>
          <PresenceFaces peers={peers} />
          <SyncChip status={state.status} />
        </div>
      </header>

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
              paneRect={readPaneRect(paneRef.current) ?? EMPTY_PANE}
              selectedIds={view.selectedIds}
              onJump={(world) => {
                const rect = readPaneRect(paneRef.current);
                if (!rect) return;
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

        {panelOpen ? (
          <div className="flex w-96 shrink-0 flex-col overflow-hidden">
            {view.activePanel === "palette" ? (
              <LibraryPalette
                onAdd={(entry) => addFromLibrary(entry.name)}
                onDragStateChange={setDragActive}
                onClose={() => openOnly(null)}
              />
            ) : null}
            {view.activePanel === "history" ? (
              <HistoryPanel
                state={state}
                onRestore={(seq) => client?.restoreTo(seq)}
                onHighlight={view.setHighlightedIds}
                onLoadFullLog={() => void client?.loadFullLog()}
                currentUserId={actorUser?.userId}
                onClose={() => openOnly(null)}
              />
            ) : null}
            {view.activePanel === "inspector" ? (
              <StateInspector
                state={state.snapshot.state}
                fragments={state.snapshot.fragments}
                onClose={() => openOnly(null)}
              />
            ) : null}
            {view.activePanel === "chat" ? (
              <SketchpadChatPanel
                sketchpadId={sketchpadId}
                sketchpadName={state.name}
                snapshot={state.snapshot}
                headSeq={state.headSeq}
                taskId={taskId}
                onClose={() => openOnly(null)}
              />
            ) : null}
          </div>
        ) : null}
      </div>

      <EditFragmentDialog
        open={editingId !== null}
        fragment={editingFragment}
        isPending={false}
        onOpenChange={(open) => setEditingId(open ? editingId : null)}
        applyLocal={applyLocal}
      />
    </div>
  );
}
