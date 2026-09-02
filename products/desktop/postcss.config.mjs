// Sentinel: stops PostCSS config discovery at this nested workspace. Without
// it, on Windows postcss-load-config's resolved backslash walk never matches
// Vite's forward-slash workspace-root stopDir, escapes past this directory and
// loads the monorepo root postcss.config.js, whose plugins aren't installed
// here — which killed the renderer build in Windows release CI.
export default { plugins: [] };
