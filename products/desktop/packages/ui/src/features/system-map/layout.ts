import type {
  SystemMap,
  SystemMapArea,
  SystemMapComponent,
} from "@posthog/core/system-map/schemas";

const COMPONENT_WIDTH = 184;
const COMPONENT_HEIGHT = 88;
const PADDING = 48;
const GAP = 64;

type Bounds = { x: number; y: number; width: number; height: number };
export type MapArea = SystemMapArea & Bounds;
export type MapComponent = SystemMapComponent & Bounds & { areaId: string };
export type MapLayout = {
  areas: MapArea[];
  components: MapComponent[];
  width: number;
  height: number;
};
export type MapConnection = {
  id: string;
  source: MapArea | MapComponent;
  target: MapArea | MapComponent;
  ids: string[];
  count: number;
  path: string;
};

function separateAreas(areas: MapArea[]): void {
  for (let i = 0; i < areas.length; i++) {
    for (let j = i + 1; j < areas.length; j++) {
      const a = areas[i];
      const b = areas[j];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const overlapX = (a.width + b.width) / 2 + GAP - Math.abs(dx);
      const overlapY = (a.height + b.height) / 2 + GAP - Math.abs(dy);
      if (overlapX <= 0 || overlapY <= 0) continue;
      if (overlapX < overlapY) {
        const shift = (overlapX / 2) * (dx < 0 ? -1 : 1);
        a.x -= shift;
        b.x += shift;
      } else {
        const shift = (overlapY / 2) * (dy < 0 ? -1 : 1);
        a.y -= shift;
        b.y += shift;
      }
    }
  }
}

export function layoutSystemMap(map: SystemMap, detailed = false): MapLayout {
  const areaByComponent = new Map(
    map.areas.flatMap((area) =>
      area.components.map((component) => [component.id, area.id]),
    ),
  );
  const degree = new Map<string, number>();
  const edges = new Map<string, { source: string; target: string }>();
  for (const link of map.relationships) {
    const source = areaByComponent.get(link.source);
    const target = areaByComponent.get(link.target);
    if (!source || !target || source === target) continue;
    const key = [source, target].sort().join(":");
    if (edges.has(key)) continue;
    edges.set(key, { source, target });
    degree.set(source, (degree.get(source) ?? 0) + 1);
    degree.set(target, (degree.get(target) ?? 0) + 1);
  }
  const areas: MapArea[] = [...map.areas]
    .sort(
      (a, b) =>
        (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0) ||
        a.id.localeCompare(b.id),
    )
    .map((area, index) => {
      const angle = index * 2.3999632297;
      const radius = Math.sqrt(index) * (detailed ? 270 : 200);
      return {
        ...area,
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius * 0.75,
        width: detailed ? (area.components.length === 1 ? 208 : 404) : 256,
        height: detailed
          ? 48 + Math.ceil(area.components.length / 2) * (COMPONENT_HEIGHT + 12)
          : 120,
      };
    });
  const byId = new Map(areas.map((area) => [area.id, area]));
  for (let step = 0; step < 180; step++) {
    for (const area of areas) {
      area.x *= 0.99;
      area.y *= 0.99;
    }
    for (const { source, target } of edges.values()) {
      const a = byId.get(source);
      const b = byId.get(target);
      if (!a || !b) continue;
      const dx = (b.x - a.x) * 0.015;
      const dy = (b.y - a.y) * 0.015;
      a.x += dx;
      a.y += dy;
      b.x -= dx;
      b.y -= dy;
    }
    separateAreas(areas);
  }
  for (let step = 0; step < 30; step++) separateAreas(areas);
  const left = Math.min(0, ...areas.map((area) => area.x - area.width / 2));
  const top = Math.min(0, ...areas.map((area) => area.y - area.height / 2));
  for (const area of areas) {
    area.x = area.x - area.width / 2 - left + PADDING;
    area.y = area.y - area.height / 2 - top + PADDING;
  }
  const components = areas.flatMap((area) =>
    area.components.map((component, index) => ({
      ...component,
      areaId: area.id,
      x: area.x + 12 + (index % 2) * (COMPONENT_WIDTH + 12),
      y: area.y + 42 + Math.floor(index / 2) * (COMPONENT_HEIGHT + 12),
      width: COMPONENT_WIDTH,
      height: COMPONENT_HEIGHT,
    })),
  );
  return {
    areas,
    components,
    width: Math.max(0, ...areas.map((area) => area.x + area.width)) + PADDING,
    height: Math.max(0, ...areas.map((area) => area.y + area.height)) + PADDING,
  };
}

function connectionPath(source: Bounds, target: Bounds): string {
  const dx = target.x + target.width / 2 - source.x - source.width / 2;
  const dy = target.y + target.height / 2 - source.y - source.height / 2;
  const horizontal =
    Math.abs(dx) / (source.width + target.width) >
    Math.abs(dy) / (source.height + target.height);
  const direction = (horizontal ? dx : dy) < 0 ? -1 : 1;
  if (horizontal) {
    const x1 = source.x + (direction > 0 ? source.width : 0);
    const y1 = source.y + source.height / 2 + 5 * direction;
    const x2 = target.x + (direction > 0 ? 0 : target.width);
    const y2 = target.y + target.height / 2 + 5 * direction;
    const bend = Math.max(32, Math.abs(x2 - x1) / 2) * direction;
    return `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`;
  }
  const x1 = source.x + source.width / 2 + 5 * direction;
  const y1 = source.y + (direction > 0 ? source.height : 0);
  const x2 = target.x + target.width / 2 + 5 * direction;
  const y2 = target.y + (direction > 0 ? 0 : target.height);
  const bend = Math.max(32, Math.abs(y2 - y1) / 2) * direction;
  return `M ${x1} ${y1} C ${x1} ${y1 + bend}, ${x2} ${y2 - bend}, ${x2} ${y2}`;
}

export function mapConnections(
  map: SystemMap,
  layout: MapLayout,
  detailed: boolean,
): MapConnection[] {
  const componentById = new Map(
    layout.components.map((node) => [node.id, node]),
  );
  const areaById = new Map(layout.areas.map((node) => [node.id, node]));
  const links = new Map<string, MapConnection>();
  for (const relationship of map.relationships) {
    const a = componentById.get(relationship.source);
    const b = componentById.get(relationship.target);
    if (!a || !b) continue;
    const source = detailed ? a : areaById.get(a.areaId);
    const target = detailed ? b : areaById.get(b.areaId);
    if (!source || !target || source.id === target.id) continue;
    const id = `${source.id}:${target.id}`;
    const existing = links.get(id);
    links.set(id, {
      id,
      source,
      target,
      count: (existing?.count ?? 0) + 1,
      ids: [
        ...new Set([...(existing?.ids ?? []), a.id, b.id, a.areaId, b.areaId]),
      ],
      path: connectionPath(source, target),
    });
  }
  return [...links.values()];
}
