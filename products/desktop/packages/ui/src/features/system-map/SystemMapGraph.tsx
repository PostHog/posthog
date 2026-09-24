import { ArrowsInSimple, Minus, Plus, Stack } from "@phosphor-icons/react";
import type { SystemMap } from "@posthog/core/system-map/schemas";
import { Button, cn, Input } from "@posthog/quill";
import {
  type ReactElement,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  type ReactZoomPanPinchRef,
  TransformComponent,
  TransformWrapper,
} from "react-zoom-pan-pinch";
import { layoutSystemMap, mapConnections } from "./layout";
import { SystemMapCard } from "./SystemMapCard";
import { SystemMapInspector } from "./SystemMapInspector";

export function SystemMapGraph({
  map,
  onInspect,
}: {
  map: SystemMap;
  onInspect?: (kind: "area" | "component") => void;
}): ReactElement {
  const markerId = useId().replace(/:/g, "");
  const transform = useRef<ReactZoomPanPinchRef>(null);
  const [scale, setScale] = useState(0.85);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const layouts = useMemo(
    () => ({
      overview: layoutSystemMap(map),
      detailed: layoutSystemMap(map, true),
    }),
    [map],
  );
  const detailed = scale >= 1;
  const layout = detailed ? layouts.detailed : layouts.overview;
  const previousLayout = useRef(layout);
  const connections = useMemo(
    () => mapConnections(map, layout, detailed),
    [map, layout, detailed],
  );
  const activeId = hoveredId ?? focusedId ?? selectedId;
  const activeComponent = layout.components.find(
    (node) => node.id === activeId,
  );
  const tracedId =
    !detailed && activeComponent ? activeComponent.areaId : activeId;
  const tracedLinks = connections.filter(
    (link) => tracedId && link.ids.includes(tracedId),
  );
  const neighbors = new Set(
    tracedLinks.flatMap((link) => [
      link.source.id,
      link.target.id,
      ...link.ids,
    ]),
  );
  if (tracedId) neighbors.add(tracedId);
  const query = search.trim().toLowerCase();
  const matches = (name: string, summary: string): boolean =>
    `${name} ${summary}`.toLowerCase().includes(query);
  const select = (id: string, kind: "area" | "component"): void => {
    setSelectedId(id);
    onInspect?.(kind);
  };

  useLayoutEffect(() => {
    const previous = previousLayout.current;
    previousLayout.current = layout;
    const controls = transform.current;
    const wrapper = controls?.instance.wrapperComponent;
    if (previous === layout || !controls || !wrapper) return;
    const { scale: zoom, positionX, positionY } = controls.state;
    const x = (wrapper.clientWidth / 2 - positionX) / zoom;
    const y = (wrapper.clientHeight / 2 - positionY) / zoom;
    const anchor = [...previous.areas].sort(
      (a, b) =>
        Math.hypot(x - a.x - a.width / 2, y - a.y - a.height / 2) -
        Math.hypot(x - b.x - b.width / 2, y - b.y - b.height / 2),
    )[0];
    const next = layout.areas.find((area) => area.id === anchor?.id);
    if (!anchor || !next) return;
    const nextX = next.x + ((x - anchor.x) / anchor.width) * next.width;
    const nextY = next.y + ((y - anchor.y) / anchor.height) * next.height;
    controls.setTransform(
      wrapper.clientWidth / 2 - nextX * zoom,
      wrapper.clientHeight / 2 - nextY * zoom,
      zoom,
      0,
    );
    setHoveredId(null);
  }, [layout]);

  const fitMap = (controls: ReactZoomPanPinchRef): void => {
    const wrapper = controls.instance.wrapperComponent;
    if (!wrapper) return;
    const { overview } = layouts;
    const fit = Math.max(
      0.05,
      Math.min(
        0.85,
        (wrapper.clientWidth - 48) / overview.width,
        (wrapper.clientHeight - 80) / overview.height,
      ),
    );
    previousLayout.current = overview;
    controls.setTransform(
      (wrapper.clientWidth - overview.width * fit) / 2,
      (wrapper.clientHeight - overview.height * fit) / 2,
      fit,
      0,
    );
    setHoveredId(null);
  };

  return (
    <div className="@container flex h-full min-h-0 flex-col text-xs">
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-border border-b px-4 py-2">
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
        <div className="relative min-h-64 min-w-0 flex-1 overflow-hidden bg-muted/20">
          <TransformWrapper
            ref={transform}
            initialScale={0.85}
            minScale={0.05}
            maxScale={2}
            onInit={fitMap}
            limitToBounds={false}
            doubleClick={{ disabled: true }}
            panning={{ excluded: ["button", "input"] }}
            onTransform={(_, state) => setScale(state.scale)}
            onPanningStart={() => setHoveredId(null)}
          >
            {(controls) => (
              <>
                <TransformComponent
                  wrapperStyle={{ width: "100%", height: "100%" }}
                >
                  <div
                    className="relative"
                    style={{ width: layout.width, height: layout.height }}
                  >
                    {detailed &&
                      layout.areas.map((area) => (
                        <div
                          key={area.id}
                          className={cn(
                            "absolute rounded-xl border border-border/60 border-dashed bg-muted/20 transition-opacity motion-reduce:transition-none",
                            tracedId && !neighbors.has(area.id) && "opacity-25",
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
                            className="flex h-9 max-w-full items-center gap-2 truncate rounded-t-xl px-3 text-muted-foreground text-xs hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary"
                            aria-pressed={selectedId === area.id}
                            onClick={() => select(area.id, "area")}
                            onPointerEnter={() => setHoveredId(area.id)}
                            onPointerLeave={() => setHoveredId(null)}
                            onFocus={() => setFocusedId(area.id)}
                            onBlur={() => setFocusedId(null)}
                          >
                            <Stack className="size-3.5 shrink-0" />
                            <span className="truncate">{area.name}</span>
                            <span className="text-[10px] tabular-nums">
                              {area.components.length}
                            </span>
                          </button>
                        </div>
                      ))}
                    <svg
                      aria-hidden="true"
                      className="pointer-events-none absolute inset-0 overflow-visible"
                      width={layout.width}
                      height={layout.height}
                    >
                      <defs>
                        {["base", "active", "muted"].map((state) => (
                          <marker
                            key={state}
                            id={`${markerId}-${state}`}
                            viewBox="0 0 10 10"
                            refX="9"
                            refY="5"
                            markerWidth="6"
                            markerHeight="6"
                            orient="auto-start-reverse"
                            className={
                              state === "active"
                                ? "text-primary"
                                : state === "muted"
                                  ? "text-muted-foreground/10"
                                  : "text-muted-foreground/40"
                            }
                          >
                            <path
                              d="M 0 0 L 10 5 L 0 10 z"
                              fill="currentColor"
                            />
                          </marker>
                        ))}
                      </defs>
                      {[...connections]
                        .sort(
                          (a, b) =>
                            Number(tracedId && a.ids.includes(tracedId)) -
                            Number(tracedId && b.ids.includes(tracedId)),
                        )
                        .map((link) => {
                          const highlighted = Boolean(
                            tracedId && link.ids.includes(tracedId),
                          );
                          return (
                            <path
                              key={link.id}
                              data-map-connection={link.id}
                              data-highlighted={highlighted}
                              d={link.path}
                              fill="none"
                              stroke="currentColor"
                              strokeWidth={highlighted ? 2 : 1.25}
                              vectorEffect="non-scaling-stroke"
                              className={cn(
                                "transition-[color,opacity] duration-150 motion-reduce:transition-none",
                                highlighted
                                  ? "text-primary"
                                  : tracedId
                                    ? "text-muted-foreground/10"
                                    : "text-muted-foreground/40",
                              )}
                              markerEnd={`url(#${markerId}-${highlighted ? "active" : tracedId ? "muted" : "base"})`}
                            />
                          );
                        })}
                    </svg>
                    {(detailed ? layout.components : layout.areas).map(
                      (node) => {
                        const isArea = "components" in node;
                        const visible =
                          matches(node.name, node.summary) ||
                          (isArea &&
                            node.components.some((component) =>
                              matches(component.name, component.summary),
                            ));
                        const count = connections
                          .filter(
                            (link) =>
                              link.source.id === node.id ||
                              link.target.id === node.id,
                          )
                          .reduce((total, link) => total + link.count, 0);
                        return (
                          <SystemMapCard
                            key={node.id}
                            node={node}
                            connections={count}
                            selected={selectedId === node.id}
                            highlighted={Boolean(
                              tracedId && neighbors.has(node.id),
                            )}
                            dimmed={
                              !visible ||
                              Boolean(tracedId && !neighbors.has(node.id))
                            }
                            showEvidence={scale >= 1.4}
                            onSelect={() =>
                              select(node.id, isArea ? "area" : "component")
                            }
                            onHover={setHoveredId}
                            onFocus={setFocusedId}
                          />
                        );
                      },
                    )}
                  </div>
                </TransformComponent>
                <div className="absolute bottom-3 left-3 flex max-w-[calc(100%-24px)] flex-wrap items-center gap-0.5 rounded-lg border border-border bg-background p-1 shadow-sm">
                  <Button
                    size="icon-sm"
                    variant="default"
                    aria-label="Zoom out"
                    title="Zoom out"
                    disabled={scale <= 0.05}
                    onClick={() => controls.zoomOut(0.2, 0)}
                  >
                    <Minus />
                  </Button>
                  <span className="w-10 text-center text-muted-foreground tabular-nums">
                    {Math.round(scale * 100)}%
                  </span>
                  <Button
                    size="icon-sm"
                    variant="default"
                    aria-label="Zoom in"
                    title="Zoom in"
                    disabled={scale >= 2}
                    onClick={() => controls.zoomIn(0.2, 0)}
                  >
                    <Plus />
                  </Button>
                  <span className="mx-1 h-4 border-border border-l" />
                  <Button
                    size="icon-sm"
                    variant="default"
                    aria-label="Fit map"
                    title="Fit map"
                    onClick={() => fitMap(controls)}
                  >
                    <ArrowsInSimple />
                  </Button>
                  <Button
                    size="sm"
                    variant="default"
                    onClick={() =>
                      detailed
                        ? fitMap(controls)
                        : controls.setTransform(
                            controls.state.positionX,
                            controls.state.positionY,
                            1.1,
                            0,
                          )
                    }
                  >
                    {detailed ? "Show areas" : "Show components"}
                  </Button>
                  <span className="px-2 text-[10px] text-muted-foreground">
                    {scale >= 1.4
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
        <SystemMapInspector
          map={map}
          selectedId={selectedId}
          onSelect={select}
          onClose={() => setSelectedId(null)}
        />
      </div>
    </div>
  );
}
