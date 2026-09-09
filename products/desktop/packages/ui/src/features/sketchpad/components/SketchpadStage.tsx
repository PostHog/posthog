import { ArrowsInIcon } from "@phosphor-icons/react";
import {
  type SketchpadPaneRect,
  type SketchpadPoint,
  screenToWorld,
} from "@posthog/core/sketchpad/sketchpadGeometry";
import type { PresencePeer } from "@posthog/core/sketchpad/sketchpadPresence";
import { Button, Kbd } from "@posthog/quill";
import {
  maxZ,
  type SketchpadFragment,
  type SketchpadFrameCaret,
  type SketchpadOp,
  type SketchpadPresenceCaret,
  type SketchpadSnapshot,
  type SketchpadTheme,
  type SketchpadViewport,
} from "@posthog/shared";
import { DropCaptureLayer } from "@posthog/ui/features/sketchpad/components/DropCaptureLayer";
import type { FragmentLastEdit } from "@posthog/ui/features/sketchpad/components/FragmentOverlay";
import { OverlayLayer } from "@posthog/ui/features/sketchpad/components/OverlayLayer";
import { PresenceLayer } from "@posthog/ui/features/sketchpad/components/PresenceLayer";
import {
  SketchpadFrame,
  type SketchpadFrameHealth,
} from "@posthog/ui/features/sketchpad/components/SketchpadFrame";
import { SketchpadHealthNotice } from "@posthog/ui/features/sketchpad/components/SketchpadHealthNotice";
import {
  useSketchpadHighlightedIds,
  useSketchpadSelectedIds,
  useSketchpadViewStore,
} from "@posthog/ui/features/sketchpad/interaction/sketchpadViewStore";
import { useSketchpadPointer } from "@posthog/ui/features/sketchpad/interaction/useSketchpadPointer";
import type { SketchpadFrameElement } from "@posthog/ui/features/sketchpad/runtime/sketchpadFrameElement";
import {
  type SketchpadFrameHandle,
  useSketchpadFrame,
} from "@posthog/ui/features/sketchpad/runtime/useSketchpadFrame";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import type { QueryClient } from "@tanstack/react-query";
import {
  type ReactElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

const DUPLICATE_OFFSET = 24;

export interface SketchpadStageProps {
  sketchpadId: string;
  paneRef: React.RefCallback<HTMLDivElement>;
  paneRect: SketchpadPaneRect;
  snapshot: SketchpadSnapshot;
  getSnapshot: () => SketchpadSnapshot;
  viewport: SketchpadViewport;
  setViewport: (viewport: SketchpadViewport) => void;
  applyLocal: (ops: SketchpadOp[], opIds?: string[]) => void;
  theme: SketchpadTheme;
  queryClient: QueryClient;
  fragmentErrors: Record<string, string>;
  onFragmentError: (id: string, message: string | null) => void;
  lastEdits: Record<string, FragmentLastEdit>;
  onEditFragment: (id: string) => void;
  dragActive: boolean;
  onDropFragment: (name: string, world: SketchpadPoint) => void;
  peers: readonly PresencePeer[];
  onCursor: (world: SketchpadPoint | null) => void;
  onCaret: (caret: SketchpadPresenceCaret | null) => void;
}

export function SketchpadStage({
  sketchpadId,
  paneRef,
  paneRect,
  snapshot,
  getSnapshot,
  viewport,
  setViewport,
  applyLocal,
  theme,
  queryClient,
  fragmentErrors,
  onFragmentError,
  lastEdits,
  onEditFragment,
  dragActive,
  onDropFragment,
  peers,
  onCursor,
  onCaret,
}: SketchpadStageProps): ReactElement {
  const [frameElement, setFrameElement] =
    useState<SketchpadFrameElement | null>(null);
  const { vendoredSketchpadModules } = useHostCapabilities();
  const [frameHealth, setFrameHealth] =
    useState<SketchpadFrameHealth>("running");
  const [stopped, setStopped] = useState(false);

  const selectedIds = useSketchpadSelectedIds();
  const highlightedIds = useSketchpadHighlightedIds();
  const focusedId = useSketchpadViewStore((state) => state.focusedId);
  const setFocusedId = useSketchpadViewStore((state) => state.setFocusedId);
  const setSelection = useSketchpadViewStore((state) => state.setSelection);
  const toggleSelection = useSketchpadViewStore(
    (state) => state.toggleSelection,
  );
  const clearSelection = useSketchpadViewStore((state) => state.clearSelection);

  const viewportRef = useRef(viewport);
  viewportRef.current = viewport;
  const selectedIdsRef = useRef(selectedIds);
  selectedIdsRef.current = selectedIds;
  const getSelectedIds = useCallback(
    (): readonly string[] => selectedIdsRef.current,
    [],
  );

  const pointer = useSketchpadPointer({
    paneRect,
    viewport,
    setViewport,
    getSnapshot,
    applyLocal,
    getSelectedIds,
    setSelection,
    toggleSelection,
  });

  const gestureActive = pointer.gesture.kind !== "none";

  const focusedRef = useRef(focusedId);
  focusedRef.current = focusedId;
  const whenOnSketchpad = useCallback(
    <T extends unknown[]>(handler: (...args: T) => void) =>
      (...args: T): void => {
        if (focusedRef.current === null) handler(...args);
      },
    [],
  );

  const paneRectRef = useRef(paneRect);
  paneRectRef.current = paneRect;
  const reportFrameCursor = useCallback(
    (clientX: number, clientY: number): void => {
      const pane = paneRectRef.current;
      onCursor(
        screenToWorld(
          { x: clientX + pane.left, y: clientY + pane.top },
          viewportRef.current,
          pane,
        ),
      );
    },
    [onCursor],
  );

  const syncedSnapshot = useRef<SketchpadSnapshot | null>(null);
  const frameRef = useRef<SketchpadFrameHandle | null>(null);
  const frame = useSketchpadFrame({
    sketchpadId,
    frameElement,
    theme,
    queryClient,
    getSnapshot,
    applyLocal,
    reportCaret: onCaret,
    events: {
      onExitFocus: () => setFocusedId(null),
      onReady: () => {
        syncedSnapshot.current = getSnapshot();
        frameRef.current?.sendInit(viewportRef.current);
        frameRef.current?.setFocus(focusedRef.current);
      },
      onFragmentRendered: (id) => onFragmentError(id, null),
      onFragmentError: (id, message) => onFragmentError(id, message),
      onStateChanged: (key, value) =>
        applyLocal([{ type: "set_state", key, value }]),
      onWheel: whenOnSketchpad(pointer.onFrameWheel),
      onBackgroundPointer: whenOnSketchpad(pointer.onFrameBackgroundPointer),
      onFragmentPointerDown: whenOnSketchpad(
        pointer.onFrameFragmentPointerDown,
      ),
      onPointerMove: reportFrameCursor,
      onPointerLeave: () => onCursor(null),
    },
  });
  frameRef.current = frame;

  const { ready, srcDoc, syncSnapshot } = frame;
  const setFrameViewport = frame.setViewport;
  const setFrameSelection = frame.setSelection;

  useEffect(() => {
    if (!ready) return;
    syncSnapshot(syncedSnapshot.current, snapshot);
    syncedSnapshot.current = snapshot;
  }, [ready, syncSnapshot, snapshot]);

  useEffect(() => {
    setFrameViewport(viewport);
  }, [setFrameViewport, viewport]);

  useEffect(() => {
    if (ready) setFrameSelection(selectedIds);
  }, [setFrameSelection, selectedIds, ready]);

  useEffect(() => {
    if (focusedId === null) return;
    if (!snapshot.fragments.some((fragment) => fragment.id === focusedId)) {
      setFocusedId(null);
    }
  }, [focusedId, setFocusedId, snapshot.fragments]);

  const setFrameFocus = frame.setFocus;
  useEffect(() => {
    setFrameFocus(focusedId);
    if (focusedId !== null) frameElement?.focus();
  }, [setFrameFocus, focusedId, frameElement]);

  const setFrameBusy = frame.setBusy;
  useEffect(() => {
    setFrameBusy(gestureActive);
  }, [setFrameBusy, gestureActive]);

  useEffect(() => {
    if (focusedId === null) return;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") setFocusedId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusedId, setFocusedId]);

  const setFrameCarets = frame.setCarets;
  const frameCarets = useMemo<SketchpadFrameCaret[]>(
    () =>
      peers.flatMap((peer) =>
        peer.carets.map((caret) => ({
          clientId: peer.clientId,
          name: peer.name,
          color: peer.color.bg,
          textColor: peer.color.text,
          key: caret.key,
          anchor: caret.anchor,
          focus: caret.focus,
        })),
      ),
    [peers],
  );

  useEffect(() => {
    if (ready) setFrameCarets(frameCarets);
  }, [setFrameCarets, frameCarets, ready]);

  const targetsOf = useCallback((id: string): string[] => {
    const selected = selectedIdsRef.current;
    return selected.includes(id) ? [...selected] : [id];
  }, []);

  const bringToFront = useCallback(
    (id: string): void => {
      const current = getSnapshot();
      const targets = targetsOf(id)
        .map((target) => current.fragments.find((f) => f.id === target))
        .filter((fragment): fragment is SketchpadFragment => Boolean(fragment))
        .sort((a, b) => a.z - b.z);
      if (targets.length === 0) return;
      applyLocal(
        targets.map((fragment) => ({
          type: "bring_to_front",
          id: fragment.id,
        })),
      );
    },
    [applyLocal, getSnapshot, targetsOf],
  );

  const removeFragment = useCallback(
    (id: string): void => {
      applyLocal(
        targetsOf(id).map((target) => ({
          type: "remove_fragment",
          id: target,
        })),
      );
      clearSelection();
    },
    [applyLocal, clearSelection, targetsOf],
  );

  const duplicateFragment = useCallback(
    (id: string): void => {
      const current = getSnapshot();
      const ops: SketchpadOp[] = [];
      const copyIds: string[] = [];
      let top = maxZ(current);
      for (const target of targetsOf(id)) {
        const source = current.fragments.find(
          (fragment) => fragment.id === target,
        );
        if (!source) continue;
        const copyId = `copy-${globalThis.crypto.randomUUID()}`;
        copyIds.push(copyId);
        top += 1;
        ops.push({
          type: "add_fragment",
          fragment: {
            ...source,
            id: copyId,
            x: source.x + DUPLICATE_OFFSET,
            y: source.y + DUPLICATE_OFFSET,
            z: top,
          },
        });
      }
      if (ops.length === 0) return;
      applyLocal(ops);
      setSelection(copyIds);
    },
    [applyLocal, getSnapshot, setSelection, targetsOf],
  );

  const toWorld = useCallback(
    (client: SketchpadPoint): SketchpadPoint =>
      screenToWorld(client, viewportRef.current, paneRect),
    [paneRect],
  );

  const ordered = useMemo(
    () => [...snapshot.fragments].sort((a, b) => a.z - b.z),
    [snapshot.fragments],
  );

  return (
    <div
      ref={paneRef}
      className="relative h-full w-full overflow-hidden"
      onWheel={whenOnSketchpad(pointer.onOverlayWheel)}
      onPointerMove={(event) =>
        onCursor(
          screenToWorld(
            { x: event.clientX, y: event.clientY },
            viewportRef.current,
            paneRectRef.current,
          ),
        )
      }
      onPointerLeave={() => onCursor(null)}
    >
      <SketchpadFrame
        onElement={setFrameElement}
        stopped={stopped}
        onHealth={setFrameHealth}
        srcDoc={srcDoc}
        vendored={vendoredSketchpadModules}
        inert={gestureActive}
      />
      <SketchpadHealthNotice
        health={frameHealth}
        stopped={stopped}
        onStop={() => {
          setStopped(true);
          setFrameHealth("running");
        }}
        onStart={() => setStopped(false)}
      />
      {focusedId === null ? (
        <OverlayLayer
          fragments={ordered}
          viewport={viewport}
          paneRect={paneRect}
          selectedIds={selectedIds}
          highlightedIds={highlightedIds}
          fragmentErrors={fragmentErrors}
          lastEdits={lastEdits}
          onStartMove={pointer.startMove}
          onStartResize={pointer.startResize}
          onEdit={onEditFragment}
          onDuplicate={duplicateFragment}
          onBringToFront={bringToFront}
          onDelete={removeFragment}
          onFocus={setFocusedId}
        />
      ) : (
        <div className="absolute bottom-4 left-4 z-[60] opacity-70 transition-opacity hover:opacity-100">
          <Button
            variant="default"
            size="sm"
            className="gap-2 rounded-full border border-(--gray-a6) bg-(--gray-1)/90 shadow-lg backdrop-blur-md"
            onClick={() => setFocusedId(null)}
          >
            <ArrowsInIcon />
            Exit full screen
            <Kbd>Esc</Kbd>
          </Button>
        </div>
      )}
      {pointer.marquee && focusedId === null ? (
        <div
          className="pointer-events-none absolute z-20 rounded-(--radius-1) border border-(--accent-a9) bg-(--accent-a2)"
          style={{
            left: pointer.marquee.left,
            top: pointer.marquee.top,
            width: pointer.marquee.width,
            height: pointer.marquee.height,
          }}
        />
      ) : null}
      {focusedId === null ? (
        <PresenceLayer
          peers={peers}
          fragments={ordered}
          viewport={viewport}
          paneRect={paneRect}
        />
      ) : null}
      <DropCaptureLayer
        active={dragActive}
        toWorld={toWorld}
        onDropFragment={onDropFragment}
      />
    </div>
  );
}
