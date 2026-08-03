import { createHash } from "node:crypto";
import path from "node:path";
import {
  CANVAS_BUILD_CONTRACT_VERSION,
  CANVAS_BUILD_TIMEOUT_MS,
  CANVAS_PLATFORM_DEPENDENCIES,
  type CanvasArtifactFile,
  type CanvasBuildAdapter,
  type CanvasBuildRequest,
  type CanvasBuildResult,
  type CanvasDiagnostic,
  type CanvasSourceProject,
  canvasRuntimeImportMap,
  canvasSourceProjectSchema,
  hasCanvasErrors,
  MAX_CANVAS_ARTIFACT_FILE_BYTES,
  MAX_CANVAS_ARTIFACT_TOTAL_BYTES,
  validateCanvasSourceProject,
} from "@posthog/shared";
import * as esbuild from "esbuild";
import { injectable } from "inversify";

// The local/dev implementation of the shared canvas build contract. It owns
// the one platform build recipe rooted at the project's entry HTML — agents
// never supply build commands. Pipeline (mirrors the plan's build stages):
//
//   1. validate the source-project schema, paths, and size limits;
//   2. resolve dependencies against the pre-admitted platform registry;
//   3. bundle every module entry with esbuild over an in-memory FS —
//      no network, no package installation, no lifecycle scripts;
//   4. rewrite the entry HTML onto the emitted, content-hashed assets and
//      inject the pinned import map for platform dependencies;
//   5. scan emitted output for size budgets and forbidden URL schemes.
//
// Local builds validate and preview only. Cloud builds run the same contract
// (and the same fixtures — see canvas-build-fixtures in @posthog/shared) and
// remain the sole source of publishable artifacts.

const MODULE_SCRIPT_RE =
  /<script\s[^>]*type\s*=\s*["']module["'][^>]*\ssrc\s*=\s*["']([^"']+)["'][^>]*>\s*<\/script>/gi;
const STYLESHEET_LINK_RE =
  /<link\s[^>]*rel\s*=\s*["']stylesheet["'][^>]*\shref\s*=\s*["']([^"']+)["'][^>]*\/?>/gi;
// Out-of-band code paths the artifact scan rejects outright.
const FORBIDDEN_SCHEME_RE =
  /(?:src|href)\s*=\s*["']\s*(javascript|data:text\/html|vbscript)/i;

const RESOLVE_EXTENSIONS = [
  "",
  ".ts",
  ".tsx",
  ".js",
  ".jsx",
  "/index.ts",
  "/index.tsx",
];

const LOADERS: Record<string, esbuild.Loader> = {
  ".ts": "ts",
  ".tsx": "tsx",
  ".js": "js",
  ".jsx": "jsx",
  ".css": "css",
  ".json": "json",
  // Inlined assets: importing an svg yields a data URL usable directly as an
  // img/css source. Binary formats need a binary source representation and
  // land with the build-service schema evolution.
  ".svg": "dataurl",
  ".txt": "text",
};

function sha256(content: string): string {
  return createHash("sha256").update(content, "utf8").digest("hex");
}

function diagnostic(
  severity: "error" | "warning",
  code: string,
  message: string,
  file?: string,
  line?: number,
): CanvasDiagnostic {
  return {
    severity,
    code,
    message,
    ...(file !== undefined ? { path: file } : {}),
    ...(line !== undefined ? { line } : {}),
  };
}

/** Normalize an HTML asset reference ("/src/main.ts", "./src/main.ts") to a project path. */
function projectPathFromRef(ref: string): string {
  return ref.replace(/^\.?\//, "");
}

/** Resolve a relative import against the importer's directory within the project. */
function resolveRelative(
  files: Record<string, unknown>,
  importer: string,
  specifier: string,
): string | null {
  const base = path.posix.normalize(
    path.posix.join(path.posix.dirname(importer), specifier),
  );
  if (base.startsWith("..")) return null;
  for (const extension of RESOLVE_EXTENSIONS) {
    const candidate = base + extension;
    if (candidate in files) return candidate;
  }
  return null;
}

@injectable()
export class CanvasBuildService implements CanvasBuildAdapter {
  async buildCanvas(request: CanvasBuildRequest): Promise<CanvasBuildResult> {
    const diagnostics: CanvasDiagnostic[] = [];

    // Stage 1 — schema + structural validation (shared with every adapter).
    const parsed = canvasSourceProjectSchema.safeParse(request.project);
    if (!parsed.success) {
      return this.failed([
        diagnostic(
          "error",
          "invalid_project",
          `the source project does not match schema version ${CANVAS_BUILD_CONTRACT_VERSION}: ${parsed.error.issues[0]?.message ?? "invalid"}`,
        ),
      ]);
    }
    const project = parsed.data;
    diagnostics.push(...validateCanvasSourceProject(project));

    // Stage 2 — dependency resolution against the pre-admitted registry.
    diagnostics.push(...this.resolveDependencies(project));
    if (hasCanvasErrors(diagnostics)) return this.failed(diagnostics);

    // Stage 3/4 — bundle and rewrite the entry HTML.
    const build = await this.bundle(project, diagnostics);
    if (build === null || hasCanvasErrors(diagnostics)) {
      return this.failed(diagnostics);
    }

    // Stage 5 — output scan: budgets and forbidden schemes.
    this.scanArtifact(build.files, diagnostics);
    if (hasCanvasErrors(diagnostics)) return this.failed(diagnostics);

    return {
      contractVersion: CANVAS_BUILD_CONTRACT_VERSION,
      status: "ready",
      diagnostics,
      manifest: {
        entryHtml: project.entryHtml,
        assets: build.files.map((file) => ({
          path: file.path,
          contentHash: file.contentHash,
          sizeBytes: file.sizeBytes,
        })),
        dependencies: project.dependencies,
        canvasSdkVersion: project.canvasSdkVersion,
        // Capability declaration/extraction lands with the cloud build
        // service; local previews run with the host bridge's own guards.
        capabilities: {
          posthog: { insights: [], inlineQueries: true, captureEvents: [] },
          network: { origins: [] },
        },
      },
      files: build.files,
    };
  }

  private failed(diagnostics: CanvasDiagnostic[]): CanvasBuildResult {
    return {
      contractVersion: CANVAS_BUILD_CONTRACT_VERSION,
      status: "failed",
      diagnostics,
    };
  }

  private resolveDependencies(
    project: CanvasSourceProject,
  ): CanvasDiagnostic[] {
    const diagnostics: CanvasDiagnostic[] = [];
    for (const [name, version] of Object.entries(project.dependencies)) {
      const admission = CANVAS_PLATFORM_DEPENDENCIES[name];
      if (!admission) {
        diagnostics.push(
          diagnostic(
            "error",
            "dependency_not_admitted",
            `dependency "${name}" is not platform-supported — supported: ${Object.keys(
              CANVAS_PLATFORM_DEPENDENCIES,
            )
              .sort()
              .join(", ")}`,
          ),
        );
      } else if (admission.version !== version) {
        diagnostics.push(
          diagnostic(
            "error",
            "dependency_version_mismatch",
            `dependency "${name}" must be the platform-pinned version ${admission.version}, got ${version}`,
          ),
        );
      }
    }
    return diagnostics;
  }

  private async bundle(
    project: CanvasSourceProject,
    diagnostics: CanvasDiagnostic[],
  ): Promise<{ files: CanvasArtifactFile[] } | null> {
    const files = project.files;
    let html = files[project.entryHtml] ?? "";

    const scriptRefs = [...html.matchAll(MODULE_SCRIPT_RE)].map((m) => m[1]);
    const styleRefs = [...html.matchAll(STYLESHEET_LINK_RE)].map((m) => m[1]);
    if (scriptRefs.length === 0 && styleRefs.length === 0) {
      diagnostics.push(
        diagnostic(
          "error",
          "no_entry_module",
          `${project.entryHtml} references no module scripts or stylesheets — nothing to build`,
          project.entryHtml,
        ),
      );
      return null;
    }

    const declaredImports = canvasRuntimeImportMap(project.dependencies);
    const artifact: CanvasArtifactFile[] = [];
    const usedImports = new Set<string>();
    const rewrites = new Map<string, string>();

    for (const ref of [...scriptRefs, ...styleRefs]) {
      const entryPath = projectPathFromRef(ref);
      if (!(entryPath in files)) {
        diagnostics.push(
          diagnostic(
            "error",
            "entry_not_found",
            `${project.entryHtml} references "${ref}" but the project has no file at ${entryPath}`,
            project.entryHtml,
          ),
        );
        continue;
      }

      const bundled = await this.bundleEntry(
        entryPath,
        files,
        project,
        declaredImports,
        usedImports,
        diagnostics,
      );
      if (bundled === null) continue;

      const extension = bundled.kind === "css" ? "css" : "js";
      const hash = sha256(bundled.content);
      const emittedPath = `assets/${path.posix
        .basename(entryPath)
        .replace(/\.[^.]+$/, "")}-${hash.slice(0, 10)}.${extension}`;
      artifact.push({
        path: emittedPath,
        content: bundled.content,
        contentHash: hash,
        sizeBytes: Buffer.byteLength(bundled.content, "utf8"),
      });
      rewrites.set(ref, `./${emittedPath}`);
      if (bundled.css !== null) {
        const cssHash = sha256(bundled.css);
        const cssPath = `assets/${path.posix
          .basename(entryPath)
          .replace(/\.[^.]+$/, "")}-${cssHash.slice(0, 10)}.css`;
        artifact.push({
          path: cssPath,
          content: bundled.css,
          contentHash: cssHash,
          sizeBytes: Buffer.byteLength(bundled.css, "utf8"),
        });
        html = html.replace(
          "</head>",
          `  <link rel="stylesheet" href="./${cssPath}" />\n</head>`,
        );
      }
    }

    if (hasCanvasErrors(diagnostics)) return null;

    for (const [ref, emitted] of rewrites) {
      html = html
        .split(`"${ref}"`)
        .join(`"${emitted}"`)
        .split(`'${ref}'`)
        .join(`'${emitted}'`);
    }

    // The import map must precede every module script so pinned platform
    // dependencies resolve; only the specifiers the build actually kept
    // external are included.
    if (usedImports.size > 0) {
      const imports = Object.fromEntries(
        Object.entries(declaredImports).filter(([specifier]) =>
          usedImports.has(specifier),
        ),
      );
      const importMap = `<script type="importmap">${JSON.stringify({ imports })}</script>`;
      html = html.includes("</head>")
        ? html.replace("</head>", `  ${importMap}\n</head>`)
        : `${importMap}\n${html}`;
    }

    const htmlHash = sha256(html);
    return {
      files: [
        {
          path: project.entryHtml,
          content: html,
          contentHash: htmlHash,
          sizeBytes: Buffer.byteLength(html, "utf8"),
        },
        ...artifact,
      ],
    };
  }

  private async bundleEntry(
    entryPath: string,
    files: Record<string, string>,
    project: CanvasSourceProject,
    declaredImports: Record<string, string>,
    usedImports: Set<string>,
    diagnostics: CanvasDiagnostic[],
  ): Promise<{
    content: string;
    css: string | null;
    kind: "js" | "css";
  } | null> {
    const isCssEntry = entryPath.endsWith(".css");
    // An in-memory FS plugin is the no-network, no-install isolation boundary:
    // only project files and pre-admitted bare specifiers can resolve.
    const virtualFs: esbuild.Plugin = {
      name: "canvas-virtual-fs",
      setup: (build) => {
        build.onResolve({ filter: /.*/ }, (args) => {
          if (args.kind === "entry-point") {
            return { path: args.path, namespace: "canvas" };
          }
          if (args.path.startsWith(".") || args.path.startsWith("/")) {
            const importer = args.importer;
            const workerImport = args.path.endsWith("?worker");
            const requestedPath = workerImport
              ? args.path.slice(0, -7)
              : args.path;
            const resolved = resolveRelative(
              files,
              importer,
              requestedPath.startsWith("/")
                ? `./${projectPathFromRef(requestedPath)}`
                : requestedPath,
            );
            if (resolved !== null) {
              return {
                path: resolved,
                namespace: workerImport ? "canvas-worker" : "canvas",
              };
            }
            const asset = resolveRelative(
              project.assets ?? {},
              importer,
              requestedPath.startsWith("/")
                ? `./${projectPathFromRef(requestedPath)}`
                : requestedPath,
            );
            if (asset === null) {
              return {
                errors: [
                  {
                    text: `cannot resolve "${args.path}" — the project has no matching file`,
                  },
                ],
              };
            }
            return { path: asset, namespace: "canvas-asset" };
          }
          // Bare specifier: must be a declared, admitted dependency (or one of
          // its runtime subpaths). Kept external and served via the import map.
          const packageName = args.path.startsWith("@")
            ? args.path.split("/").slice(0, 2).join("/")
            : args.path.split("/")[0];
          if (!(packageName in project.dependencies)) {
            return {
              errors: [
                {
                  text: `import_not_declared: "${args.path}" is not in the project's dependencies`,
                },
              ],
            };
          }
          if (!(args.path in declaredImports)) {
            return {
              errors: [
                {
                  text: `import_not_declared: "${args.path}" is not an admitted entry point of ${packageName}`,
                },
              ],
            };
          }
          usedImports.add(args.path);
          return { path: args.path, external: true };
        });
        build.onLoad({ filter: /.*/, namespace: "canvas" }, (args) => {
          const contents = files[args.path];
          if (contents === undefined) return null;
          const loader = LOADERS[path.posix.extname(args.path)] ?? "text";
          return { contents, loader, resolveDir: "/" };
        });
        build.onLoad({ filter: /.*/, namespace: "canvas-asset" }, (args) => {
          const asset = project.assets?.[args.path];
          if (!asset) return null;
          return {
            contents: Uint8Array.from(Buffer.from(asset.content, "base64")),
            loader:
              asset.contentType === "application/wasm" ||
              asset.contentType === "application/octet-stream"
                ? "binary"
                : "dataurl",
          };
        });
        build.onLoad(
          { filter: /.*/, namespace: "canvas-worker" },
          async (args) => {
            const source = files[args.path];
            if (source === undefined) return null;
            const compiled = await this.bundleEntry(
              args.path,
              files,
              project,
              declaredImports,
              usedImports,
              diagnostics,
            );
            if (compiled === null) return null;
            return {
              contents: `export default URL.createObjectURL(new Blob([${JSON.stringify(compiled.content)}],{type:"text/javascript"}));`,
              loader: "js",
            };
          },
        );
      },
    };

    try {
      const result = await Promise.race([
        esbuild.build({
          entryPoints: [entryPath],
          bundle: true,
          write: false,
          format: "esm",
          platform: "browser",
          target: "es2022",
          jsx: "automatic",
          minify: true,
          sourcemap: false,
          logLevel: "silent",
          outdir: "out",
          plugins: [virtualFs],
        }),
        new Promise<never>((_, reject) =>
          setTimeout(
            () =>
              reject(
                new Error(`build timed out after ${CANVAS_BUILD_TIMEOUT_MS}ms`),
              ),
            CANVAS_BUILD_TIMEOUT_MS,
          ).unref?.(),
        ),
      ]);

      let js: string | null = null;
      let css: string | null = null;
      for (const file of result.outputFiles ?? []) {
        if (file.path.endsWith(".css")) css = file.text;
        else js = file.text;
      }
      if (isCssEntry) {
        return { content: css ?? "", css: null, kind: "css" };
      }
      return { content: js ?? "", css, kind: "js" };
    } catch (error) {
      for (const issue of this.esbuildIssues(error)) {
        // Surface the specific import_not_declared code the virtual FS raised;
        // everything else is a bundle error at the reported location.
        const isUndeclared = issue.text.startsWith("import_not_declared:");
        diagnostics.push(
          diagnostic(
            "error",
            isUndeclared ? "import_not_declared" : "bundle_error",
            isUndeclared
              ? issue.text.replace("import_not_declared: ", "")
              : issue.text,
            issue.file ?? entryPath,
            issue.line,
          ),
        );
      }
      return null;
    }
  }

  private esbuildIssues(
    error: unknown,
  ): { text: string; file?: string; line?: number }[] {
    if (
      typeof error === "object" &&
      error !== null &&
      "errors" in error &&
      Array.isArray((error as esbuild.BuildFailure).errors)
    ) {
      return (error as esbuild.BuildFailure).errors.map((message) => ({
        text: message.text,
        // esbuild reports virtual-FS locations as "<namespace>:<path>".
        file: message.location?.file?.replace(/^canvas:/, "") ?? undefined,
        line: message.location?.line,
      }));
    }
    return [{ text: error instanceof Error ? error.message : String(error) }];
  }

  private scanArtifact(
    files: CanvasArtifactFile[],
    diagnostics: CanvasDiagnostic[],
  ): void {
    let total = 0;
    for (const file of files) {
      total += file.sizeBytes;
      if (file.sizeBytes > MAX_CANVAS_ARTIFACT_FILE_BYTES) {
        diagnostics.push(
          diagnostic(
            "error",
            "artifact_too_large",
            `emitted file exceeds the ${MAX_CANVAS_ARTIFACT_FILE_BYTES / 1024} KB per-file budget`,
            file.path,
          ),
        );
      }
      if (
        file.path.endsWith(".html") &&
        FORBIDDEN_SCHEME_RE.test(file.content)
      ) {
        diagnostics.push(
          diagnostic(
            "error",
            "forbidden_url_scheme",
            "the artifact references a forbidden URL scheme (javascript:, vbscript:, or data:text/html)",
            file.path,
          ),
        );
      }
    }
    if (total > MAX_CANVAS_ARTIFACT_TOTAL_BYTES) {
      diagnostics.push(
        diagnostic(
          "error",
          "artifact_too_large",
          `the artifact exceeds the ${MAX_CANVAS_ARTIFACT_TOTAL_BYTES / 1024} KB total budget`,
        ),
      );
    }
  }
}
