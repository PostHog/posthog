import { ArrowsLeftRight, Cube, Stack } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import type { ReactElement } from "react";
import type { MapArea, MapComponent } from "./layout";

export function SystemMapCard({
  node,
  connections,
  selected,
  highlighted,
  dimmed,
  showEvidence,
  onSelect,
  onHover,
  onFocus,
}: {
  node: MapArea | MapComponent;
  connections: number;
  selected: boolean;
  highlighted: boolean;
  dimmed: boolean;
  showEvidence: boolean;
  onSelect: () => void;
  onHover: (id: string | null) => void;
  onFocus: (id: string | null) => void;
}): ReactElement {
  const area = "components" in node;
  const Icon = area ? Stack : Cube;
  return (
    <button
      type="button"
      aria-label={node.name}
      aria-pressed={selected}
      title={`${node.name}\n${node.summary}`}
      data-map-node={node.id}
      data-highlighted={highlighted || selected}
      onClick={onSelect}
      onPointerEnter={() => onHover(node.id)}
      onPointerLeave={() => onHover(null)}
      onFocus={() => onFocus(node.id)}
      onBlur={() => onFocus(null)}
      className={cn(
        "absolute z-10 flex flex-col rounded-lg border bg-background text-left shadow-sm transition-[border-color,box-shadow,opacity] duration-150 focus-visible:outline-2 focus-visible:outline-primary motion-reduce:transition-none",
        area ? "gap-2 p-3" : "gap-1 p-2.5",
        selected
          ? "border-primary ring-2 ring-primary/20"
          : highlighted
            ? "border-primary/60 shadow-md"
            : "border-border hover:border-primary/60",
        dimmed && "opacity-25",
      )}
      style={{
        left: node.x,
        top: node.y,
        width: node.width,
        height: node.height,
      }}
    >
      <span className="flex min-w-0 shrink-0 items-center gap-2">
        <Icon
          aria-hidden="true"
          className={cn(
            "size-4 shrink-0",
            highlighted || selected ? "text-primary" : "text-muted-foreground",
          )}
        />
        <span
          className={cn("truncate font-medium", area ? "text-sm" : "text-xs")}
        >
          {node.name}
        </span>
      </span>
      <span className="line-clamp-2 shrink-0 text-muted-foreground text-xs leading-[1.25]">
        {node.summary}
      </span>
      <span className="mt-auto flex min-w-0 shrink-0 items-center justify-between gap-2 text-[10px] text-muted-foreground leading-none">
        {!area && showEvidence ? (
          <code className="truncate text-primary" title={node.evidence[0].path}>
            {node.evidence[0].path.split("/").at(-1)}:{node.evidence[0].line}
          </code>
        ) : (
          <span>
            {area
              ? `${node.components.length} ${node.components.length === 1 ? "component" : "components"}`
              : `${node.operations.length} ${node.operations.length === 1 ? "operation" : "operations"}`}
          </span>
        )}
        <span
          className="flex shrink-0 items-center gap-1"
          title={`${connections} connections`}
        >
          <ArrowsLeftRight aria-hidden="true" className="size-3" />
          <span>{connections}</span>
        </span>
      </span>
    </button>
  );
}
