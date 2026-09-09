import {
  panBy,
  type ResizeHandle,
  rectFromPoints,
  rectsTouch,
  resizeRect,
  SKETCHPAD_MIN_FRAGMENT_SIZE,
  type SketchpadPaneRect,
  type SketchpadPoint,
  type SketchpadRect,
  type SketchpadScreenRect,
  screenToWorld,
  snapToGrid,
  zoomAround,
} from "@posthog/core/sketchpad/sketchpadGeometry";
import type {
  SketchpadFrameToHostMessage,
  SketchpadOp,
  SketchpadSnapshot,
  SketchpadViewport,
} from "@posthog/shared";
import { useCallback, useEffect, useRef, useState } from "react";

export type SketchpadGesture =
  | { kind: "none" }
  | { kind: "pan" }
  | { kind: "marquee" }
  | { kind: "move"; ids: string[] }
  | { kind: "resize"; id: string; handle: ResizeHandle };

export interface UseSketchpadPointerOptions {
  paneRect: SketchpadPaneRect;
  viewport: SketchpadViewport;
  setViewport: (v: SketchpadViewport) => void;
  getSnapshot: () => SketchpadSnapshot;
  applyLocal: (ops: SketchpadOp[]) => void;
  getSelectedIds: () => readonly string[];
  setSelection: (ids: string[]) => void;
  toggleSelection: (id: string) => void;
}

export interface SketchpadPointerHandle {
  gesture: SketchpadGesture;
  marquee: SketchpadScreenRect | null;
  onFrameWheel(
    e: Extract<SketchpadFrameToHostMessage, { type: "wheel" }>,
  ): void;
  onFrameBackgroundPointer(
    e: Extract<SketchpadFrameToHostMessage, { type: "background-pointer" }>,
  ): void;
  onFrameFragmentPointerDown(
    e: Extract<SketchpadFrameToHostMessage, { type: "fragment-pointer-down" }>,
  ): void;
  onOverlayWheel(e: React.WheelEvent): void;
  startMove(id: string, e: React.PointerEvent): void;
  startResize(id: string, handle: ResizeHandle, e: React.PointerEvent): void;
}

const CLICK_SLOP_PX = 3;
const ZOOM_WHEEL_SCALE = 300;
const MIDDLE_BUTTON = 1;

interface DragItem {
  id: string;
  origin: SketchpadRect;
}

interface DragState {
  pointerId: number;
  target: HTMLElement;
  start: SketchpadPoint;
  items: DragItem[];
  origin: SketchpadRect;
  sent: SketchpadRect;
}

interface MarqueeState {
  start: SketchpadPoint;
  current: SketchpadPoint;
  base: string[];
  travel: number;
}

type ActiveGesture =
  | { kind: "pan"; current: SketchpadPoint; travel: number }
  | (MarqueeState & { kind: "marquee" })
  | (DragState & { kind: "move"; ids: string[] })
  | (DragState & { kind: "resize"; id: string; handle: ResizeHandle });

interface PointerModifiers {
  shiftKey: boolean;
  metaKey: boolean;
  ctrlKey: boolean;
}

export function useSketchpadPointer(
  o: UseSketchpadPointerOptions,
): SketchpadPointerHandle {
  const latest = useRef(o);
  latest.current = o;

  const [gesture, setGesture] = useState<SketchpadGesture>({ kind: "none" });
  const [marquee, setMarquee] = useState<SketchpadScreenRect | null>(null);
  const activeGesture = useRef<ActiveGesture | null>(null);
  const readPane = useCallback(
    (): SketchpadPaneRect => latest.current.paneRect,
    [],
  );
  const finish = useCallback((): void => {
    const active = activeGesture.current;
    if (
      active &&
      (active.kind === "move" || active.kind === "resize") &&
      active.target.hasPointerCapture(active.pointerId)
    ) {
      active.target.releasePointerCapture(active.pointerId);
    }
    activeGesture.current = null;
    setMarquee(null);
    setGesture({ kind: "none" });
  }, []);

  const zoomOrPan = useCallback(
    (e: {
      deltaX: number;
      deltaY: number;
      ctrlKey: boolean;
      metaKey: boolean;
      clientX: number;
      clientY: number;
    }): void => {
      const { viewport, setViewport } = latest.current;
      if (e.ctrlKey || e.metaKey) {
        const factor = Math.exp(-e.deltaY / ZOOM_WHEEL_SCALE);
        setViewport(
          zoomAround(
            viewport,
            { x: e.clientX, y: e.clientY },
            factor,
            readPane(),
          ),
        );
        return;
      }
      setViewport(panBy(viewport, -e.deltaX, -e.deltaY));
    },
    [readPane],
  );

  const onFrameWheel = useCallback(
    (e: Extract<SketchpadFrameToHostMessage, { type: "wheel" }>): void => {
      const pane = readPane();
      zoomOrPan({
        deltaX: e.deltaX,
        deltaY: e.deltaY,
        ctrlKey: e.ctrlKey,
        metaKey: e.metaKey,
        clientX: e.clientX + pane.left,
        clientY: e.clientY + pane.top,
      });
    },
    [readPane, zoomOrPan],
  );

  const onOverlayWheel = useCallback(
    (e: React.WheelEvent): void => {
      zoomOrPan({
        deltaX: e.deltaX,
        deltaY: e.deltaY,
        ctrlKey: e.ctrlKey,
        metaKey: e.metaKey,
        clientX: e.clientX,
        clientY: e.clientY,
      });
    },
    [zoomOrPan],
  );

  const commitMarquee = useCallback(
    (state: MarqueeState): void => {
      const { viewport, getSnapshot, setSelection } = latest.current;
      const pane = readPane();
      const world = rectFromPoints(
        screenToWorld(state.start, viewport, pane),
        screenToWorld(state.current, viewport, pane),
      );
      const hits = getSnapshot()
        .fragments.filter((fragment) => rectsTouch(world, fragment))
        .map((fragment) => fragment.id);
      const next = [...state.base];
      for (const id of hits) if (!next.includes(id)) next.push(id);
      setSelection(next);
    },
    [readPane],
  );

  const continueBackground = useCallback(
    (point: SketchpadPoint, phase: "move" | "up"): void => {
      const active = activeGesture.current;
      if (!active || (active.kind !== "pan" && active.kind !== "marquee"))
        return;
      const dx = point.x - active.current.x;
      const dy = point.y - active.current.y;
      active.current = point;
      active.travel += Math.abs(dx) + Math.abs(dy);
      if (phase === "move") {
        if (active.kind === "marquee")
          setMarquee(paneRelativeRect(active, readPane()));
        else {
          const { viewport, setViewport } = latest.current;
          setViewport(panBy(viewport, dx, dy));
        }
        return;
      }
      if (active.kind === "marquee") {
        if (active.travel <= CLICK_SLOP_PX)
          latest.current.setSelection(active.base);
        else commitMarquee(active);
      }
      finish();
    },
    [commitMarquee, finish, readPane],
  );

  const onFrameBackgroundPointer = useCallback(
    (
      e: Extract<SketchpadFrameToHostMessage, { type: "background-pointer" }>,
    ): void => {
      const pane = readPane();
      const point = { x: e.clientX + pane.left, y: e.clientY + pane.top };

      if (e.phase !== "down") {
        continueBackground(point, e.phase);
        return;
      }
      if (e.button === MIDDLE_BUTTON || e.altKey) {
        finish();
        activeGesture.current = { kind: "pan", current: point, travel: 0 };
        setGesture({ kind: "pan" });
        return;
      }
      if (e.button !== 0) return;
      finish();
      activeGesture.current = {
        kind: "marquee",
        start: point,
        current: point,
        base: e.shiftKey ? [...latest.current.getSelectedIds()] : [],
        travel: 0,
      };
      setGesture({ kind: "marquee" });
    },
    [continueBackground, readPane, finish],
  );

  const onFrameFragmentPointerDown = useCallback(
    (
      e: Extract<
        SketchpadFrameToHostMessage,
        { type: "fragment-pointer-down" }
      >,
    ): void => {
      const { getSelectedIds, setSelection, toggleSelection } = latest.current;
      if (isAdditive(e)) {
        toggleSelection(e.id);
        return;
      }
      if (getSelectedIds().includes(e.id)) return;
      setSelection([e.id]);
    },
    [],
  );

  const beginDrag = useCallback(
    (
      e: React.PointerEvent,
      items: DragItem[],
      origin: SketchpadRect,
      gesture: Extract<SketchpadGesture, { kind: "move" | "resize" }>,
    ): void => {
      const target = e.currentTarget as HTMLElement;
      e.preventDefault();
      e.stopPropagation();
      finish();
      target.setPointerCapture(e.pointerId);
      activeGesture.current = {
        ...gesture,
        pointerId: e.pointerId,
        target,
        start: { x: e.clientX, y: e.clientY },
        items,
        origin,
        sent: origin,
      };
      setGesture(gesture);
    },
    [finish],
  );

  const startMove = useCallback(
    (id: string, e: React.PointerEvent): void => {
      const { getSnapshot, getSelectedIds, setSelection, toggleSelection } =
        latest.current;
      if (isAdditive(e)) {
        e.stopPropagation();
        toggleSelection(id);
        return;
      }
      const fragments = getSnapshot().fragments;
      const pressed = fragments.find((fragment) => fragment.id === id);
      if (!pressed) return;

      const selected = getSelectedIds();
      const ids = selected.includes(id) ? [...selected] : [id];
      if (!selected.includes(id)) setSelection(ids);

      const items: DragItem[] = [];
      for (const target of ids) {
        const fragment = fragments.find((candidate) => candidate.id === target);
        if (fragment) items.push({ id: fragment.id, origin: boxOf(fragment) });
      }
      beginDrag(e, items, boxOf(pressed), {
        kind: "move",
        ids: items.map((item) => item.id),
      });
    },
    [beginDrag],
  );

  const startResize = useCallback(
    (id: string, handle: ResizeHandle, e: React.PointerEvent): void => {
      const { getSnapshot, setSelection } = latest.current;
      const fragment = getSnapshot().fragments.find(
        (candidate) => candidate.id === id,
      );
      if (!fragment) return;
      setSelection([id]);
      const origin = boxOf(fragment);
      beginDrag(e, [{ id, origin }], origin, { kind: "resize", id, handle });
    },
    [beginDrag],
  );

  useEffect(() => {
    const onPointerMove = (event: PointerEvent): void => {
      const active = activeGesture.current;
      if (!active) return;
      if (active.kind === "pan" || active.kind === "marquee") {
        continueBackground({ x: event.clientX, y: event.clientY }, "move");
        return;
      }
      const state = active;
      if (state.pointerId !== event.pointerId) return;

      const { viewport, applyLocal } = latest.current;
      const dx = (event.clientX - state.start.x) / viewport.zoom;
      const dy = (event.clientY - state.start.y) / viewport.zoom;
      const next =
        active.kind === "move"
          ? { ...state.origin, x: state.origin.x + dx, y: state.origin.y + dy }
          : resizeRect(
              state.origin,
              active.handle,
              dx,
              dy,
              SKETCHPAD_MIN_FRAGMENT_SIZE,
            );
      const snapped: SketchpadRect = {
        x: snapToGrid(next.x),
        y: snapToGrid(next.y),
        w: snapToGrid(next.w),
        h: snapToGrid(next.h),
      };
      if (sameRect(snapped, state.sent)) return;
      state.sent = snapped;

      if (active.kind === "resize") {
        applyLocal([
          {
            type: "update_fragment",
            id: active.id,
            patch: {
              x: snapped.x,
              y: snapped.y,
              w: snapped.w,
              h: snapped.h,
            },
          },
        ]);
        return;
      }

      const moveX = snapped.x - state.origin.x;
      const moveY = snapped.y - state.origin.y;
      applyLocal(
        state.items.map((item) => ({
          type: "update_fragment",
          id: item.id,
          patch: { x: item.origin.x + moveX, y: item.origin.y + moveY },
        })),
      );
    };

    const onPointerUp = (event: PointerEvent): void => {
      const active = activeGesture.current;
      if (!active) return;
      if (active.kind === "pan" || active.kind === "marquee") {
        continueBackground({ x: event.clientX, y: event.clientY }, "up");
      } else if (active.pointerId === event.pointerId) finish();
    };
    const onPointerCancel = (event: PointerEvent): void => {
      const active = activeGesture.current;
      if (!active) return;
      if (
        active.kind === "pan" ||
        active.kind === "marquee" ||
        active.pointerId === event.pointerId
      )
        finish();
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerCancel);
    window.addEventListener("blur", finish);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerCancel);
      window.removeEventListener("blur", finish);
      finish();
    };
  }, [continueBackground, finish]);

  return {
    gesture,
    marquee,
    onFrameWheel,
    onFrameBackgroundPointer,
    onFrameFragmentPointerDown,
    onOverlayWheel,
    startMove,
    startResize,
  };
}

function boxOf(fragment: SketchpadRect): SketchpadRect {
  return { x: fragment.x, y: fragment.y, w: fragment.w, h: fragment.h };
}

function isAdditive(modifiers: PointerModifiers): boolean {
  return modifiers.shiftKey || modifiers.metaKey || modifiers.ctrlKey;
}

function paneRelativeRect(
  state: MarqueeState,
  pane: SketchpadPaneRect,
): SketchpadScreenRect {
  const rect = rectFromPoints(state.start, state.current);
  return {
    left: rect.x - pane.left,
    top: rect.y - pane.top,
    width: rect.w,
    height: rect.h,
  };
}

function sameRect(a: SketchpadRect, b: SketchpadRect): boolean {
  return a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;
}
