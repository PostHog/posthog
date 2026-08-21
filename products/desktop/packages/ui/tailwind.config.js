import { radixThemePreset } from "radix-themes-tw";

/** @type {import('tailwindcss').Config} */
module.exports = {
  presets: [radixThemePreset],
  content: [
    "./src/**/*.{js,ts,jsx,tsx}",
    "../../apps/code/src/**/*.{ts,tsx}",
    "../../apps/code/index.html",
    "../../apps/web/src/**/*.{ts,tsx}",
    "../../apps/web/index.html",
  ],
  theme: {
    extend: {
      animation: {
        "sync-rotate": "sync-rotate 3s ease-in-out infinite",
      },
      keyframes: {
        "sync-rotate": {
          "0%": { transform: "rotate(0deg)" },
          "33%": { transform: "rotate(0deg)" },
          "66%": { transform: "rotate(360deg)" },
          "100%": { transform: "rotate(360deg)" },
        },
      },
      colors: {
        posthog: {
          orange: "#f54d00",
          yellow: "#f8be2a",
          50: "#fef2f2",
          100: "#fee2e2",
          200: "#fecaca",
          300: "#fca5a5",
          400: "#f87171",
          500: "#ef4444",
          600: "#dc2626",
          700: "#b91c1c",
          800: "#991b1b",
          900: "#7f1d1d",
        },
      },
      // radix-themes-tw replaces Tailwind's lineHeight scale with `{ 1: var(--line-height-1), … 9: var(--line-height-9) }`,
      // which silently drops the named utilities (`leading-tight`, `leading-snug`, `leading-normal`, …). Re-add them so
      // utilities written against the standard Tailwind names continue to apply.
      lineHeight: {
        none: "1",
        tight: "1.25",
        snug: "1.375",
        normal: "1.5",
        relaxed: "1.625",
        loose: "2",
      },
      // fontFamily lives in globals.css `@theme` (--font-sans / --font-mono)
      // — the Tailwind v4 source of truth. Don't re-declare here.
    },
  },
  plugins: [],
  darkMode: "class",
};
