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
  paneRef: React.RefObject<HTMLElement | null>;
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

interface PanState {
  last: SketchpadPoint;
  travel: number;
}

interface MarqueeState {
  start: SketchpadPoint;
  current: SketchpadPoint;
  base: string[];
  travel: number;
}

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
  const drag = useRef<DragState | null>(null);
  const pan = useRef<PanState | null>(null);
  const marqueeRef = useRef<MarqueeState | null>(null);

  const readPane = useCallback(
    (): SketchpadPaneRect => readPaneRect(latest.current.paneRef.current),
    [],
  );

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

  const endMarquee = useCallback((): void => {
    marqueeRef.current = null;
    setMarquee(null);
  }, []);

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
      const pane = readPane();
      const e = { phase } as const;

      const marqueeActive = marqueeRef.current;
      if (marqueeActive) {
        const dx = point.x - marqueeActive.current.x;
        const dy = point.y - marqueeActive.current.y;
        marqueeActive.current = point;
        marqueeActive.travel += Math.abs(dx) + Math.abs(dy);
        if (e.phase === "move") {
          setMarquee(paneRelativeRect(marqueeActive, pane));
          return;
        }
        if (marqueeActive.travel <= CLICK_SLOP_PX) {
          latest.current.setSelection(marqueeActive.base);
        } else {
          commitMarquee(marqueeActive);
        }
        endMarquee();
        setGesture({ kind: "none" });
        return;
      }

      const active = pan.current;
      if (!active) return;

      const dx = point.x - active.last.x;
      const dy = point.y - active.last.y;

      if (e.phase === "move") {
        active.last = point;
        active.travel += Math.abs(dx) + Math.abs(dy);
        const { viewport, setViewport } = latest.current;
        setViewport(panBy(viewport, dx, dy));
        return;
      }

      pan.current = null;
      setGesture({ kind: "none" });
    },
    [commitMarquee, endMarquee, readPane],
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
        pan.current = { last: point, travel: 0 };
        setGesture({ kind: "pan" });
        return;
      }
      if (e.button !== 0) return;
      marqueeRef.current = {
        start: point,
        current: point,
        base: e.shiftKey ? [...latest.current.getSelectedIds()] : [],
        travel: 0,
      };
      setGesture({ kind: "marquee" });
    },
    [continueBackground, readPane],
  );

  const backgroundActive = gesture.kind === "pan" || gesture.kind === "marquee";
  useEffect(() => {
    if (!backgroundActive) return;
    const move = (event: PointerEvent): void =>
      continueBackground({ x: event.clientX, y: event.clientY }, "move");
    const end = (event: PointerEvent): void =>
      continueBackground({ x: event.clientX, y: event.clientY }, "up");
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
    };
  }, [backgroundActive, continueBackground]);

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

  useEffect(() => {
    const drop = (): void => {
      if (!pan.current && !marqueeRef.current) return;
      pan.current = null;
      endMarquee();
      setGesture({ kind: "none" });
    };
    window.addEventListener("blur", drop);
    return () => window.removeEventListener("blur", drop);
  }, [endMarquee]);

  const beginDrag = useCallback(
    (e: React.PointerEvent, items: DragItem[], origin: SketchpadRect): void => {
      const target = e.currentTarget as HTMLElement;
      e.preventDefault();
      e.stopPropagation();
      target.setPointerCapture(e.pointerId);
      drag.current = {
        pointerId: e.pointerId,
        target,
        start: { x: e.clientX, y: e.clientY },
        items,
        origin,
        sent: origin,
      };
    },
    [],
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
      beginDrag(e, items, boxOf(pressed));
      setGesture({ kind: "move", ids: items.map((item) => item.id) });
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
      beginDrag(e, [{ id, origin }], origin);
      setGesture({ kind: "resize", id, handle });
    },
    [beginDrag],
  );

  useEffect(() => {
    const active = gesture;
    if (active.kind !== "move" && active.kind !== "resize") return;

    const onPointerMove = (event: PointerEvent): void => {
      const state = drag.current;
      if (!state || state.pointerId !== event.pointerId) return;

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
      const state = drag.current;
      if (state && state.pointerId === event.pointerId) {
        if (state.target.hasPointerCapture(event.pointerId)) {
          state.target.releasePointerCapture(event.pointerId);
        }
        drag.current = null;
      }
      setGesture({ kind: "none" });
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
    };
  }, [gesture]);

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

export function readPaneRect(element: HTMLElement | null): SketchpadPaneRect {
  if (!element) return { left: 0, top: 0, width: 0, height: 0 };
  const rect = element.getBoundingClientRect();
  return {
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
  };
}

export function clientToWorld(
  point: SketchpadPoint,
  viewport: SketchpadViewport,
  element: HTMLElement | null,
): SketchpadPoint {
  return screenToWorld(point, viewport, readPaneRect(element));
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
