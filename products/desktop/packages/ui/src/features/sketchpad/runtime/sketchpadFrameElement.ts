import {
  type HostToSketchpadFrameMessage,
  SKETCHPAD_FRAME_NAME,
  SKETCHPAD_FRAME_TO_HOST_CHANNEL,
  SKETCHPAD_HOST_TO_FRAME_CHANNEL,
  SKETCHPAD_PARTITION,
  SKETCHPAD_URL,
} from "@posthog/shared";
import { SKETCHPAD_FRAME_TITLE } from "@posthog/ui/features/sketchpad/sketchpadCopy";

export interface SketchpadWebviewElement extends HTMLElement {
  send(channel: string, message: unknown): void;
  getWebContentsId(): number;
}

interface WebviewIpcMessageEvent extends Event {
  channel: string;
  args: unknown[];
}

export type SketchpadFrameElement = HTMLIFrameElement | SketchpadWebviewElement;

export function isSketchpadWebview(
  element: SketchpadFrameElement | null,
): element is SketchpadWebviewElement {
  return element?.tagName.toLowerCase() === "webview";
}

export function createSketchpadWebview(): SketchpadWebviewElement {
  const webview = document.createElement("webview") as SketchpadWebviewElement;
  webview.setAttribute("partition", SKETCHPAD_PARTITION);
  webview.setAttribute("src", SKETCHPAD_URL);
  webview.setAttribute("name", SKETCHPAD_FRAME_NAME);
  webview.setAttribute("aria-label", SKETCHPAD_FRAME_TITLE);
  webview.className = "absolute inset-0 h-full w-full border-0";
  return webview;
}

export function sendToSketchpadFrame(
  element: SketchpadFrameElement | null,
  message: HostToSketchpadFrameMessage,
): void {
  if (!element) return;
  if (isSketchpadWebview(element)) {
    element.send(SKETCHPAD_HOST_TO_FRAME_CHANNEL, message);
    return;
  }
  element.contentWindow?.postMessage(message, "*");
}

export function listenToSketchpadFrame(
  element: SketchpadFrameElement,
  onMessage: (data: unknown) => void,
): () => void {
  if (!isSketchpadWebview(element)) {
    const listener = (event: MessageEvent): void => {
      if (event.source !== (element as HTMLIFrameElement).contentWindow) return;
      onMessage(event.data);
    };
    window.addEventListener("message", listener);
    return () => window.removeEventListener("message", listener);
  }
  const listener = (event: Event): void => {
    const ipc = event as WebviewIpcMessageEvent;
    if (ipc.channel !== SKETCHPAD_FRAME_TO_HOST_CHANNEL) return;
    onMessage(ipc.args[0]);
  };
  element.addEventListener("ipc-message", listener);
  return () => element.removeEventListener("ipc-message", listener);
}
