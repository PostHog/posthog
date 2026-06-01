// Allow side-effect imports of plain CSS files (next/types/global.d.ts only
// declares the *.module.css variant). Next 15's typecheck pass runs with
// `noUncheckedSideEffectImports` semantics, so without this the
// `import '../src/styles/globals.css'` in app/layout.tsx fails the build.
declare module '*.css'
