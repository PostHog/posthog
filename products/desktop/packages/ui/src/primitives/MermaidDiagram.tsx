import { cn, Spinner } from "@posthog/quill";
import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import type { Mermaid } from "mermaid";
import { useEffect, useId, useState } from "react";

let mermaidModule: Promise<Mermaid> | null = null;
let initializedDarkMode: boolean | null = null;

// Rendering runs dagre layout and builds thousands of SVG nodes on the main
// thread, so a session that is reopened reuses its diagrams instead.
const RENDER_CACHE_MAX = 50;
const renderCache = new Map<string, string>();

function renderCacheKey(code: string, isDarkMode: boolean): string {
  return `${isDarkMode ? "dark" : "light"}\n${code}`;
}

function rememberRender(key: string, svg: string): void {
  if (renderCache.size >= RENDER_CACHE_MAX) {
    const oldest = renderCache.keys().next().value;
    if (oldest !== undefined) renderCache.delete(oldest);
  }
  renderCache.set(key, svg);
}

function loadMermaid(): Promise<Mermaid> {
  mermaidModule ??= import("mermaid").then((module) => module.default);
  return mermaidModule;
}

// The `img` key of a shape metadata block, as in `A@{ img: "…" }`. Mermaid reads the key
// case sensitively today, but matching either case keeps the guard off that detail.
const IMAGE_NODE =
  /(?:^|[,{\s])["']?img["']?\s*:\s*(?<url>"[^"]*"|'[^']*'|[^,}\n]*)/gi;

// Mermaid loads an image node through `new Image()` while it builds the SVG, before
// DOMPurify ever sees the output. Diagrams reach us from PR comments and agent output, so
// a remote image node would let their author make the app fetch any URL.
function hasRemoteImageNode(code: string): boolean {
  for (const node of code.matchAll(IMAGE_NODE)) {
    const url = node.groups?.url?.trim() ?? "";
    if (!/^["']?data:/i.test(url)) return true;
  }
  return false;
}

async function renderDiagram(
  id: string,
  code: string,
  isDarkMode: boolean,
): Promise<string> {
  if (hasRemoteImageNode(code)) {
    throw new Error("image nodes can't load remote URLs");
  }
  const mermaid = await loadMermaid();
  if (initializedDarkMode !== isDarkMode) {
    mermaid.initialize({
      startOnLoad: false,
      theme: isDarkMode ? "dark" : "default",
      securityLevel: "strict",
      suppressErrorRendering: true,
      fontFamily: "inherit",
    });
    initializedDarkMode = isDarkMode;
  }
  const { svg } = await mermaid.render(id, code);
  rememberRender(renderCacheKey(code, isDarkMode), svg);
  return svg;
}

type DiagramState =
  | { status: "loading" }
  | { status: "ready"; svg: string }
  | { status: "error"; message: string };

interface MermaidDiagramProps {
  code: string;
  className?: string;
}

export function MermaidDiagram({ code, className }: MermaidDiagramProps) {
  const isDarkMode = useThemeStore((s) => s.isDarkMode);
  const diagramId = `mermaid-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const [state, setState] = useState<DiagramState>(() => {
    const svg = renderCache.get(renderCacheKey(code, isDarkMode));
    return svg ? { status: "ready", svg } : { status: "loading" };
  });

  useEffect(() => {
    const cached = renderCache.get(renderCacheKey(code, isDarkMode));
    if (cached) {
      setState({ status: "ready", svg: cached });
      return;
    }
    let cancelled = false;
    renderDiagram(diagramId, code, isDarkMode)
      .then((svg) => {
        if (!cancelled) setState({ status: "ready", svg });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const message =
          error instanceof Error ? error.message : "Unknown error";
        setState({ status: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [code, diagramId, isDarkMode]);

  if (state.status === "error") {
    return (
      <div className={className} data-testid="mermaid-error">
        <p className="mb-1 text-(--red-11) text-xs">
          Couldn't render this Mermaid diagram: {state.message}
        </p>
        <CodeBlock size="1">{code}</CodeBlock>
      </div>
    );
  }

  if (state.status === "loading") {
    return (
      <div
        className={cn("mb-3 flex justify-center py-4", className)}
        data-testid="mermaid-loading"
      >
        <Spinner />
      </div>
    );
  }

  return (
    <div
      className={cn("mb-3 overflow-x-auto", className)}
      data-testid="mermaid-diagram"
      // biome-ignore lint/security/noDangerouslySetInnerHtml: mermaid runs the SVG through DOMPurify in strict mode
      dangerouslySetInnerHTML={{ __html: state.svg }}
    />
  );
}
