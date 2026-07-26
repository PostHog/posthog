# HTML, browser APIs, and WebGL

Prefer semantic HTML and local CSS for documents and focused experiences that do not need a component framework. Put
JavaScript or TypeScript in a local module file referenced by `index.html`; inline and remote scripts are rejected.

Direct Canvas and WebGL APIs need no dependency. For Three.js, declare the admitted exact version:

```json
{
  "three": "0.183.2"
}
```

Use responsive sizing and release animation frames, observers, and event listeners during teardown when the application
creates them. Keep all emitted assets inside the source project or import them through the module graph.
