import { SKETCHPAD_FRAME_NAME } from "@posthog/shared";
import {
  createSketchpadWebview,
  type SketchpadFrameElement,
} from "@posthog/ui/features/sketchpad/runtime/sketchpadFrameElement";
import { SKETCHPAD_FRAME_TITLE } from "@posthog/ui/features/sketchpad/sketchpadCopy";
import { type ReactElement, useEffect, useRef } from "react";

interface SketchpadFrameProps {
  onElement: (element: SketchpadFrameElement | null) => void;
  srcDoc: string;
  vendored: boolean;
  inert: boolean;
  stopped: boolean;
  onHealth?: (health: SketchpadFrameHealth) => void;
}

export type SketchpadFrameHealth = "running" | "busy" | "gone";

export function SketchpadFrame({
  onElement,
  srcDoc,
  vendored,
  inert,
  stopped,
  onHealth,
}: SketchpadFrameProps): ReactElement {
  const mountRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!vendored || stopped) return;
    const mount = mountRef.current;
    if (!mount) return;
    const webview = createSketchpadWebview();
    const busy = (): void => onHealth?.("busy");
    const running = (): void => onHealth?.("running");
    const gone = (): void => onHealth?.("gone");
    webview.addEventListener("unresponsive", busy);
    webview.addEventListener("responsive", running);
    webview.addEventListener("render-process-gone", gone);
    mount.appendChild(webview);
    onElement(webview);
    return () => {
      webview.removeEventListener("unresponsive", busy);
      webview.removeEventListener("responsive", running);
      webview.removeEventListener("render-process-gone", gone);
      webview.remove();
      onElement(null);
    };
  }, [vendored, stopped, onElement, onHealth]);

  const inertClass = inert ? "pointer-events-none" : "";

  if (vendored) {
    return (
      <div
        ref={mountRef}
        className={`absolute inset-0 h-full w-full ${inertClass}`}
      />
    );
  }

  return (
    <iframe
      ref={onElement}
      title={SKETCHPAD_FRAME_TITLE}
      name={SKETCHPAD_FRAME_NAME}
      sandbox="allow-scripts"
      allow=""
      referrerPolicy="no-referrer"
      srcDoc={srcDoc}
      className={`absolute inset-0 h-full w-full border-0 ${inertClass}`}
    />
  );
}
