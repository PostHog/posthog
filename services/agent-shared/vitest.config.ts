import { defineConfig } from 'vitest/config'

export default defineConfig({
    // Backend service — no CSS to process. Without this stub, Vite walks up
    // to the repo-root postcss.config.js (Tailwind), which a filtered CI
    // install hasn't pulled @tailwindcss/postcss for.
    css: { postcss: { plugins: [] } },
    test: {
        include: ['src/**/*.test.ts'],
        testTimeout: 10_000,
        globals: true,
    },
})
