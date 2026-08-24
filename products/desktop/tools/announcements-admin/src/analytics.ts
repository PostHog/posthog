import posthog from "posthog-js";

const apiKey = import.meta.env.VITE_POSTHOG_API_KEY;

export function initAnalytics(): void {
  if (!apiKey) return;
  posthog.init(apiKey, {
    api_host: import.meta.env.VITE_POSTHOG_API_HOST,
    ui_host: import.meta.env.VITE_POSTHOG_UI_HOST,
    autocapture: false,
    capture_pageview: false,
    capture_pageleave: false,
    disable_session_recording: true,
  });
}

export function capture(
  event: string,
  properties?: Record<string, unknown>,
): void {
  if (!apiKey) return;
  posthog.capture(event, properties);
}

export function captureException(error: unknown): void {
  if (!apiKey) return;
  posthog.captureException(error);
}

export function identify(distinctId: string, label?: string): void {
  if (!apiKey) return;
  posthog.identify(distinctId, label ? { name: label } : undefined);
}
