import {
  CANVAS_BUILD_CONTRACT_FIXTURES,
  CANVAS_ENTRY_HTML,
  CANVAS_FIXTURE_REACT_IMPORTS,
  type CanvasBuildResult,
  createCanvasStarterProject,
} from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { CanvasBuildService } from "./canvas-build";

const service = new CanvasBuildService();

function build(
  project = createCanvasStarterProject(),
): Promise<CanvasBuildResult> {
  return service.buildCanvas({ project, mode: "validate" });
}

describe("CanvasBuildService", () => {
  // The shared contract fixtures are the drift guard between this local
  // adapter and the cloud build service: both must produce these outcomes.
  it.each(CANVAS_BUILD_CONTRACT_FIXTURES.map((f) => [f.name, f] as const))(
    "contract fixture: %s",
    async (_name, fixture) => {
      const result = await service.buildCanvas({
        project: fixture.project,
        mode: "validate",
      });
      expect(result.status).toBe(fixture.expected.status);
      for (const code of fixture.expected.diagnosticCodes ?? []) {
        expect(result.diagnostics.map((d) => d.code)).toContain(code);
      }
      if (fixture.expected.status === "failed") {
        expect(result.files).toBeUndefined();
      }
    },
  );

  it("emits compiled, content-hashed assets and rewrites the entry html", async () => {
    const result = await build();

    expect(result.status).toBe("ready");
    const files = result.files ?? [];
    const html = files.find((f) => f.path === CANVAS_ENTRY_HTML);
    const js = files.find((f) => f.path.endsWith(".js"));
    const css = files.find((f) => f.path.endsWith(".css"));
    expect(html && js && css).toBeTruthy();

    // No runtime compilation: the artifact references the emitted chunk, not
    // the TypeScript source, and the chunk is plain JS.
    expect(html?.content).not.toContain("src/main.ts");
    expect(html?.content).toContain(js?.path ?? "");
    expect(js?.content).toContain("New canvas");
    expect(js?.content).not.toContain(": string");

    // Assets are content-addressed and the manifest mirrors them.
    expect(js?.path).toMatch(
      new RegExp(`-${js?.contentHash.slice(0, 10)}\\.js$`),
    );
    expect(result.manifest?.assets.map((a) => a.path)).toEqual(
      files.map((f) => f.path),
    );
    expect(result.manifest?.entryHtml).toBe(CANVAS_ENTRY_HTML);
  });

  it("bundles multi-file react projects and pins platform deps via the import map", async () => {
    const fixture = CANVAS_BUILD_CONTRACT_FIXTURES.find(
      (f) => f.name === "react + quill application",
    );
    if (!fixture) throw new Error("react fixture missing");
    const result = await service.buildCanvas({
      project: fixture.project,
      mode: "validate",
    });

    expect(result.status).toBe("ready");
    const html = result.files?.find((f) => f.path === CANVAS_ENTRY_HTML);
    const js = result.files?.find((f) => f.path.endsWith(".js"));
    // App.tsx was bundled into the entry chunk — one module graph, no
    // per-file loading and no browser Babel.
    expect(js?.content).toContain("clicked");
    // Platform deps stay external, resolved by the injected pinned import map.
    const importMap = html?.content.match(
      /<script type="importmap">(.*?)<\/script>/s,
    );
    expect(importMap).toBeTruthy();
    const imports = Object.keys(JSON.parse(importMap?.[1] ?? "{}").imports);
    for (const specifier of [
      "react",
      "react-dom/client",
      "react/jsx-runtime",
    ]) {
      expect(CANVAS_FIXTURE_REACT_IMPORTS).toContain(specifier);
      expect(imports).toContain(specifier);
    }
    // Only what the build kept external is offered to the runtime.
    expect(imports).not.toContain("dayjs");
  });

  it("inlines svg and json asset imports into the bundle", async () => {
    const fixture = CANVAS_BUILD_CONTRACT_FIXTURES.find(
      (f) => f.name === "asset imports (svg data-url + json)",
    );
    if (!fixture) throw new Error("asset fixture missing");
    const result = await service.buildCanvas({
      project: fixture.project,
      mode: "validate",
    });

    expect(result.status).toBe("ready");
    const js = result.files?.find((f) => f.path.endsWith(".js"));
    // The svg became a data URL and the json a literal — no asset fetches at
    // runtime and nothing left for the sandbox CSP to block.
    expect(js?.content).toContain("data:image/svg+xml");
    expect(js?.content).toContain("hedgehog");
  });

  it("builds binary assets and self-contained module workers", async () => {
    const project = createCanvasStarterProject();
    project.files["src/main.ts"] =
      'import image from "../assets/pixel.png"; import workerUrl from "./worker.ts?worker"; document.body.dataset.image = image; new Worker(workerUrl, { type: "module" });';
    project.files["src/worker.ts"] =
      'import { value } from "./worker-lib"; self.postMessage(value);';
    project.files["src/worker-lib.ts"] = "export const value = 42;";
    project.assets = {
      "assets/pixel.png": {
        encoding: "base64",
        contentType: "image/png",
        content: "iVBORw0KGgo=",
      },
      "assets/module.wasm": {
        encoding: "base64",
        contentType: "application/wasm",
        content: "AGFzbQEAAAA=",
      },
    };

    const result = await build(project);

    expect(result.status).toBe("ready");
    const js = result.files?.find((file) => file.path.endsWith(".js"));
    expect(js?.content).toContain("new Blob");
    expect(js?.content).toContain("data:image/png;base64");
    expect(js?.content).not.toContain("worker-lib");
    expect(js?.content).toContain("42");
  });

  it("reports bundle errors with the failing file and line", async () => {
    const project = createCanvasStarterProject();
    project.files["src/main.ts"] =
      "const ok = 1;\nconst broken = {;\nexport {};";

    const result = await build(project);

    expect(result.status).toBe("failed");
    const error = result.diagnostics.find((d) => d.code === "bundle_error");
    expect(error?.path).toBe("src/main.ts");
    expect(error?.line).toBe(2);
  });
});
