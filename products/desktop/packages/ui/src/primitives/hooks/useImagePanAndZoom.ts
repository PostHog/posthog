import {
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

interface UseImagePanAndZoomOptions {
  minScale?: number;
  maxScale?: number;
}

interface UseImagePanAndZoomResult {
  containerRef: RefObject<HTMLDivElement | null>;
  transform: string;
  isZoomed: boolean;
  isDragging: boolean;
  reset: () => void;
}

interface ZoomState {
  scale: number;
  tx: number;
  ty: number;
}

const IDENTITY: ZoomState = { scale: 1, tx: 0, ty: 0 };

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function useImagePanAndZoom(
  options: UseImagePanAndZoomOptions = {},
): UseImagePanAndZoomResult {
  const minScale = options.minScale ?? 1;
  const maxScale = options.maxScale ?? 8;

  const containerRef = useRef<HTMLDivElement | null>(null);
  const [state, setState] = useState<ZoomState>(IDENTITY);
  const [isDragging, setIsDragging] = useState(false);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    let drag: {
      pointerId: number;
      startX: number;
      startY: number;
      startTx: number;
      startTy: number;
    } | null = null;

    const handleWheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        const rect = el.getBoundingClientRect();
        const cursorX = event.clientX - (rect.left + rect.width / 2);
        const cursorY = event.clientY - (rect.top + rect.height / 2);
        setState((prev) => {
          const nextScale = clamp(
            prev.scale * Math.exp(-event.deltaY * 0.01),
            minScale,
            maxScale,
          );
          if (nextScale === prev.scale) return prev;
          if (nextScale === 1) return IDENTITY;
          const ratio = nextScale / prev.scale;
          return {
            scale: nextScale,
            tx: cursorX - (cursorX - prev.tx) * ratio,
            ty: cursorY - (cursorY - prev.ty) * ratio,
          };
        });
        return;
      }
      if (stateRef.current.scale <= 1) return;
      event.preventDefault();
      setState((prev) => ({
        scale: prev.scale,
        tx: prev.tx - event.deltaX,
        ty: prev.ty - event.deltaY,
      }));
    };

    const handlePointerDown = (event: PointerEvent) => {
      if (event.button !== 0) return;
      if (stateRef.current.scale <= 1) return;
      el.setPointerCapture(event.pointerId);
      drag = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        startTx: stateRef.current.tx,
        startTy: stateRef.current.ty,
      };
      setIsDragging(true);
    };

    const handlePointerMove = (event: PointerEvent) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      const dx = event.clientX - drag.startX;
      const dy = event.clientY - drag.startY;
      const startTx = drag.startTx;
      const startTy = drag.startTy;
      setState((prev) => ({
        scale: prev.scale,
        tx: startTx + dx,
        ty: startTy + dy,
      }));
    };

    const handlePointerUp = (event: PointerEvent) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      if (el.hasPointerCapture(event.pointerId)) {
        el.releasePointerCapture(event.pointerId);
      }
      drag = null;
      setIsDragging(false);
    };

    const handleDoubleClick = () => setState(IDENTITY);

    el.addEventListener("wheel", handleWheel, { passive: false });
    el.addEventListener("pointerdown", handlePointerDown);
    el.addEventListener("pointermove", handlePointerMove);
    el.addEventListener("pointerup", handlePointerUp);
    el.addEventListener("pointercancel", handlePointerUp);
    el.addEventListener("dblclick", handleDoubleClick);

    return () => {
      el.removeEventListener("wheel", handleWheel);
      el.removeEventListener("pointerdown", handlePointerDown);
      el.removeEventListener("pointermove", handlePointerMove);
      el.removeEventListener("pointerup", handlePointerUp);
      el.removeEventListener("pointercancel", handlePointerUp);
      el.removeEventListener("dblclick", handleDoubleClick);
    };
  }, [minScale, maxScale]);

  const reset = useCallback(() => setState(IDENTITY), []);

  return {
    containerRef,
    transform: `translate(${state.tx}px, ${state.ty}px) scale(${state.scale})`,
    isZoomed: state.scale > 1,
    isDragging,
    reset,
  };
}
