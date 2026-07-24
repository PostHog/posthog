import "@testing-library/jest-dom";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom does not implement PointerEvent; pointer-driven UI hooks (e.g.
// useImagePanAndZoom) rely on `pointerId` propagating from pointerdown through
// pointermove. Provide a MouseEvent-backed polyfill that carries it.
if (typeof globalThis.PointerEvent === "undefined") {
  class JsdomPointerEvent extends MouseEvent {
    pointerId: number;
    pointerType: string;
    width: number;
    height: number;
    pressure: number;
    tangentialPressure: number;
    tiltX: number;
    tiltY: number;
    twist: number;
    isPrimary: boolean;

    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 0;
      this.pointerType = init.pointerType ?? "";
      this.width = init.width ?? 1;
      this.height = init.height ?? 1;
      this.pressure = init.pressure ?? 0;
      this.tangentialPressure = init.tangentialPressure ?? 0;
      this.tiltX = init.tiltX ?? 0;
      this.tiltY = init.tiltY ?? 0;
      this.twist = init.twist ?? 0;
      this.isPrimary = init.isPrimary ?? false;
    }
  }
  globalThis.PointerEvent = JsdomPointerEvent as unknown as typeof PointerEvent;
}

// Node 26 defines an experimental `localStorage` global that is disabled
// without --localstorage-file, and vitest's jsdom window leaves localStorage
// undefined in its presence; zustand persist stores under test need a working
// implementation, so back both globals with an in-memory Storage.
if (typeof window.localStorage?.setItem !== "function") {
  const store = new Map<string, string>();
  const localStoragePolyfill: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key) => store.get(key) ?? null,
    key: (index) => [...store.keys()][index] ?? null,
    removeItem: (key) => {
      store.delete(key);
    },
    setItem: (key, value) => {
      store.set(key, String(value));
    },
  };
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: localStoragePolyfill,
  });
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: localStoragePolyfill,
  });
}

// jsdom does not implement ResizeObserver; @dnd-kit/dom instantiates one at
// module load, so components using useSortable/useDroppable need a stub.
if (typeof globalThis.ResizeObserver === "undefined") {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver =
    ResizeObserverStub as unknown as typeof ResizeObserver;
}

// jsdom does not implement Element.getAnimations. With ResizeObserver stubbed
// above, Base UI's ScrollAreaViewport now mounts fully and schedules a timer
// that calls viewport.getAnimations() — which would otherwise throw an
// uncaught exception after the test tears down (any component using a Base UI
// scroll area, e.g. menus/modals). Return no running animations.
if (typeof Element.prototype.getAnimations !== "function") {
  Element.prototype.getAnimations = () => [];
}

// jsdom does not implement matchMedia; UI stores (e.g. themeStore) read it at
// module load to resolve the system color scheme.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

afterEach(() => {
  cleanup();
});
