import { ArrowsInSimple, Minus, Plus, X } from "@phosphor-icons/react";
import type { SystemMap } from "@posthog/core/system-map/schemas";
import { Button, cn, Input } from "@posthog/quill";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import { type ReactElement, useId, useMemo, useState } from "react";
import { TransformComponent, TransformWrapper } from "react-zoom-pan-pinch";
import { layoutSystemMap, mapConnections } from "./layout";
import {
  ConnectionAssumptions,
  Evidence,
  PublicOperations,
  ScanCoverage,
} from "./SystemMapDetails";

export function SystemMapGraph({
  map,
  onInspect,
}: {
  map: SystemMap;
  onInspect?: (kind: "area" | "component") => void;
}): ReactElement {
  const markerId = useId().replace(/:/g, "");
  const [scale, setScale] = useState(0.55);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const layout = useMemo(() => layoutSystemMap(map), [map]);
  const detailed = scale >= 0.7;
  const evidenceVisible = scale >= 1.15;
  const connections = useMemo(
    () => mapConnections(map, detailed),
    [map, detailed],
  );
  const selectedArea = map.areas.find((area) => area.id === selectedId);
  const selectedComponent = layout.components.find(
    (component) => component.id === selectedId,
  );
  const selected = selectedArea ?? selectedComponent;
  const selectedComponents = new Set(
    selectedArea?.components.map((component) => component.id) ??
      (selectedComponent ? [selectedComponent.id] : []),
  );
  const related = map.relationships.filter(
    (link) =>
      selectedComponents.has(link.source) ||
      selectedComponents.has(link.target),
  );
  const componentNames = new Map(
    layout.components.map((component) => [component.id, component.name]),
  );
  const matches = (name: string, summary: string): boolean =>
    `${name} ${summary}`.toLowerCase().includes(search.toLowerCase());
  const select = (id: string, kind: "area" | "component"): void => {
    setSelectedId(id);
    onInspect?.(kind);
  };

  return (
    <div className="@container flex h-full min-h-0 flex-col text-xs">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-border border-b px-4 py-2">
        <Input
          aria-label="Find an area or component"
          placeholder="Find an area or component"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="w-60 max-w-full"
        />
        <span className="text-muted-foreground">
          {map.areas.length} areas · {layout.components.length} components ·{" "}
          {map.relationships.length} connections
        </span>
      </div>
      <div className="flex min-h-0 flex-1 @max-[780px]:flex-col">
        <div className="relative min-h-64 min-w-0 flex-1 overflow-hidden bg-background">
          <TransformWrapper
            initialScale={0.55}
            minScale={0.05}
            maxScale={2}
            centerOnInit
            onInit={({ instance, centerView }) => {
              const wrapper = instance.wrapperComponent;
              if (wrapper)
                centerView(
                  Math.max(
                    0.05,
                    Math.min(
                      0.65,
                      (wrapper.clientWidth / layout.width) * 0.9,
                      (wrapper.clientHeight / layout.height) * 0.9,
                    ),
                  ),
                  0,
                );
            }}
            limitToBounds={false}
            doubleClick={{ disabled: true }}
            panning={{ excluded: ["button", "input"] }}
            onTransform={(_, state) => setScale(state.scale)}
          >
            {({ zoomIn, zoomOut, centerView, setTransform, instance }) => (
              <>
                <TransformComponent
                  wrapperStyle={{ width: "100%", height: "100%" }}
                >
                  <div
                    className="relative"
                    style={{ width: layout.width, height: layout.height }}
                  >
                    {layout.areas.map((area) => (
                      <div
                        key={area.id}
                        className={cn(
                          "absolute rounded-xl border border-border bg-muted/30",
                          selectedId === area.id &&
                            "border-primary ring-2 ring-primary/20",
                        )}
                        style={{
                          left: area.x,
                          top: area.y,
                          width: area.width,
                          height: area.height,
                        }}
                      >
                        <button
                          type="button"
                          className={cn(
                            "w-full rounded-t-xl px-5 py-4 text-left focus-visible:outline-2 focus-visible:outline-primary",
                            !matches(area.name, area.summary) &&
                              !area.components.some((component) =>
                                matches(component.name, component.summary),
                              ) &&
                              "opacity-30",
                          )}
                          aria-pressed={selectedId === area.id}
                          onClick={() => select(area.id, "area")}
                        >
                          <span className="block font-semibold text-2xl">
                            {area.name}
                          </span>
                          <span className="block text-muted-foreground text-sm">
                            {area.components.length} components
                          </span>
                        </button>
                        {!detailed && (
                          <p className="max-w-md px-5 py-6 text-muted-foreground text-xl">
                            {area.summary}
                          </p>
                        )}
                      </div>
                    ))}
                    <svg
                      aria-hidden="true"
                      className="pointer-events-none absolute inset-0 overflow-visible"
                      width={layout.width}
                      height={layout.height}
                    >
                      <defs>
                        <marker
                          id={markerId}
                          viewBox="0 0 10 10"
                          refX="9"
                          refY="5"
                          markerWidth="7"
                          markerHeight="7"
                          orient="auto-start-reverse"
                        >
                          <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
                        </marker>
                      </defs>
                      {connections.map((link) => (
                        <path
                          key={link.id}
                          d={link.path}
                          fill="none"
                          stroke="currentColor"
                          strokeWidth={
                            selectedId && link.ids.includes(selectedId)
                              ? 3
                              : 1.5
                          }
                          className={cn(
                            selectedId && link.ids.includes(selectedId)
                              ? "text-primary"
                              : "text-muted-foreground/35",
                          )}
                          markerEnd={`url(#${markerId})`}
                        />
                      ))}
                    </svg>
                    {detailed &&
                      layout.components.map((component) => (
                        <button
                          type="button"
                          key={component.id}
                          aria-pressed={selectedId === component.id}
                          onClick={() => select(component.id, "component")}
                          className={cn(
                            "absolute overflow-hidden rounded-lg border border-border bg-background p-3 text-left shadow-sm focus-visible:outline-2 focus-visible:outline-primary",
                            selectedId === component.id &&
                              "border-primary ring-2 ring-primary/20",
                            !matches(component.name, component.summary) &&
                              "opacity-30",
                          )}
                          style={{
                            left: component.x,
                            top: component.y,
                            width: component.width,
                            height: component.height,
                          }}
                        >
                          <span className="block truncate font-medium text-sm">
                            {component.name}
                          </span>
                          <span className="mt-1 line-clamp-3 block text-muted-foreground text-xs">
                            {component.summary}
                          </span>
                          {evidenceVisible && (
                            <code className="mt-2 block truncate text-[10px] text-primary">
                              {component.evidence[0].path}:
                              {component.evidence[0].line}
                            </code>
                          )}
                        </button>
                      ))}
                  </div>
                </TransformComponent>
                <div className="absolute bottom-3 left-3 flex max-w-[calc(100%-24px)] flex-wrap items-center gap-1 rounded-lg border border-border bg-background p-1 shadow-sm">
                  <Button
                    size="icon"
                    variant="default"
                    aria-label="Zoom out"
                    disabled={scale <= 0.05}
                    onClick={() => zoomOut(0.25)}
                  >
                    <Minus />
                  </Button>
                  <span className="w-12 text-center tabular-nums">
                    {Math.round(scale * 100)}%
                  </span>
                  <Button
                    size="icon"
                    variant="default"
                    aria-label="Zoom in"
                    disabled={scale >= 2}
                    onClick={() => zoomIn(0.25)}
                  >
                    <Plus />
                  </Button>
                  <Button
                    size="icon"
                    variant="default"
                    aria-label="Fit map"
                    onClick={() => {
                      const wrapper = instance.wrapperComponent;
                      const fit = wrapper
                        ? Math.min(
                            wrapper.clientWidth / layout.width,
                            wrapper.clientHeight / layout.height,
                          ) * 0.9
                        : 0.55;
                      centerView(Math.max(0.05, Math.min(fit, 1)));
                    }}
                  >
                    <ArrowsInSimple />
                  </Button>
                  <Button
                    size="sm"
                    variant="default"
                    onClick={() =>
                      setTransform(
                        instance.state.positionX,
                        instance.state.positionY,
                        detailed ? 0.55 : 0.9,
                      )
                    }
                  >
                    {detailed ? "Show areas" : "Show components"}
                  </Button>
                  <span className="px-2 text-muted-foreground">
                    {evidenceVisible
                      ? "Source files"
                      : detailed
                        ? "Components"
                        : "Areas"}
                  </span>
                </div>
              </>
            )}
          </TransformWrapper>
        </div>
        <aside
          aria-label="Map details"
          className="flex @max-[780px]:max-h-[40%] @max-[780px]:w-full w-80 shrink-0 flex-col border-border @max-[780px]:border-t border-l @max-[780px]:border-l-0 bg-background"
        >
          <ChromeBar
            actions={
              selected ? (
                <Button
                  size="icon"
                  variant="default"
                  aria-label="Close details"
                  onClick={() => setSelectedId(null)}
                >
                  <X />
                </Button>
              ) : undefined
            }
          >
            <span className="truncate font-medium">
              {selected?.name ?? "System overview"}
            </span>
          </ChromeBar>
          <div className="min-h-0 space-y-5 overflow-y-auto p-4">
            <p>{selected?.summary ?? map.summary}</p>
            {!selected && (
              <>
                <p className="text-muted-foreground">
                  Scroll to zoom. Drag the map to move it. Select an area to
                  inspect its components and connections.
                </p>
                <div className="space-y-1">
                  {map.areas.map((area) => (
                    <Button
                      key={area.id}
                      variant="default"
                      size="sm"
                      className="w-full justify-start"
                      onClick={() => select(area.id, "area")}
                    >
                      {area.name}
                    </Button>
                  ))}
                </div>
                <ScanCoverage map={map} onSelect={select} />
                {map.limitations.length > 0 && (
                  <section>
                    <h3 className="mb-2 font-medium">Analysis limits</h3>
                    <ul className="list-disc space-y-2 pl-4 text-muted-foreground">
                      {map.limitations.map((limit) => (
                        <li key={limit}>{limit}</li>
                      ))}
                    </ul>
                  </section>
                )}
                <p className="text-muted-foreground">
                  This map is an agent interpretation. Check the source evidence
                  before you use it to change code.
                </p>
              </>
            )}
            {selectedArea && (
              <section>
                <h3 className="mb-2 font-medium">Components</h3>
                <div className="space-y-1">
                  {selectedArea.components.map((component) => (
                    <Button
                      key={component.id}
                      size="sm"
                      variant="default"
                      className="w-full justify-start"
                      onClick={() => select(component.id, "component")}
                    >
                      {component.name}
                    </Button>
                  ))}
                </div>
              </section>
            )}
            {selectedComponent && (
              <>
                <section>
                  <h3 className="mb-2 font-medium">Source evidence</h3>
                  <Evidence items={selectedComponent.evidence} />
                </section>
                <PublicOperations component={selectedComponent} />
              </>
            )}
            {selected && (
              <section>
                <h3 className="mb-2 font-medium">Connections</h3>
                {related.length === 0 ? (
                  <p className="text-muted-foreground">
                    No connections were found in the inspected source.
                  </p>
                ) : (
                  <ul className="space-y-4">
                    {related.map((link, index) => (
                      <li
                        key={`${link.source}:${link.target}:${index}`}
                        className="space-y-2 border-border border-b pb-3"
                      >
                        <div className="flex flex-wrap items-center gap-1">
                          <Button
                            size="sm"
                            variant="default"
                            onClick={() => select(link.source, "component")}
                          >
                            {componentNames.get(link.source)}
                          </Button>
                          <span className="text-muted-foreground">
                            → {link.kind} →
                          </span>
                          <Button
                            size="sm"
                            variant="default"
                            onClick={() => select(link.target, "component")}
                          >
                            {componentNames.get(link.target)}
                          </Button>
                        </div>
                        <p>{link.summary}</p>
                        <Evidence items={link.evidence} />
                        <ConnectionAssumptions assumptions={link.assumptions} />
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
