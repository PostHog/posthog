import { cn, Spinner } from "@posthog/quill";
import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import type { Mermaid } from "mermaid";
import { useEffect, useId, useState } from "react";

let mermaidModule: Promise<Mermaid> | null = null;
let initializedDarkMode: boolean | null = null;

function loadMermaid(): Promise<Mermaid> {
  mermaidModule ??= import("mermaid").then((module) => module.default);
  return mermaidModule;
}

async function renderDiagram(
  id: string,
  code: string,
  isDarkMode: boolean,
): Promise<string> {
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
  const [state, setState] = useState<DiagramState>({ status: "loading" });

  useEffect(() => {
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
