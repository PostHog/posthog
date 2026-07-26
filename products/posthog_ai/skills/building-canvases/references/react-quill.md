# React and Quill canvases

Use React for stateful, application-like experiences. Use `@posthog/quill` for accessible controls and layouts that
should match PostHog.

Declare exact versions for every imported package. The admitted React starter dependencies are:

```json
{
  "@posthog/quill": "0.3.0-beta.24",
  "react": "19.2.6",
  "react-dom": "19.2.6"
}
```

Mount React from a local module entry referenced by `index.html`. Keep styles and components in separate project files
when that makes the source easier to maintain. The build bundles dependencies, so do not load React, Tailwind, or other
scripts from a CDN.

Quill is optional. A React application can use semantic elements and local CSS when the design system adds no value.
