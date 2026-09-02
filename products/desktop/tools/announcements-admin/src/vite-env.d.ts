/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_POSTHOG_API_KEY?: string;
  readonly VITE_POSTHOG_API_HOST?: string;
  readonly VITE_POSTHOG_UI_HOST?: string;
}

/** Hoggie PNG file stems, injected from vite.config.ts at build time. */
declare const __HOGGIE_FILES__: string[];
