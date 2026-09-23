import type { SystemMap } from "@posthog/core/system-map/schemas";

export const AREA_WIDTH = 520;
export const COMPONENT_WIDTH = 230;
export const COMPONENT_HEIGHT = 126;
const GAP = 110;

export function layoutSystemMap(map: SystemMap) {
  const columns = Math.min(3, Math.ceil(Math.sqrt(map.areas.length)));
  const rowHeight = Math.max(
    ...map.areas.map(
      (area) =>
        110 + Math.ceil(area.components.length / 2) * (COMPONENT_HEIGHT + 16),
    ),
  );
  const areas = map.areas.map((area, index) => ({
    ...area,
    x: 60 + (index % columns) * (AREA_WIDTH + GAP),
    y: 60 + Math.floor(index / columns) * (rowHeight + GAP),
    width: AREA_WIDTH,
    height: rowHeight,
  }));
  const components = areas.flatMap((area) =>
    area.components.map((component, index) => ({
      ...component,
      areaId: area.id,
      x: area.x + 20 + (index % 2) * (COMPONENT_WIDTH + 20),
      y: area.y + 90 + Math.floor(index / 2) * (COMPONENT_HEIGHT + 16),
      width: COMPONENT_WIDTH,
      height: COMPONENT_HEIGHT,
    })),
  );
  return {
    areas,
    components,
    width: columns * (AREA_WIDTH + GAP) + 10,
    height: Math.ceil(areas.length / columns) * (rowHeight + GAP) + 10,
  };
}

export function mapConnections(map: SystemMap, detailed: boolean) {
  const layout = layoutSystemMap(map);
  const componentById = new Map(
    layout.components.map((component) => [component.id, component]),
  );
  const areaById = new Map(layout.areas.map((area) => [area.id, area]));
  const links = new Map<
    string,
    {
      source: { x: number; y: number; width: number; height: number };
      target: { x: number; y: number; width: number; height: number };
      ids: string[];
      count: number;
    }
  >();
  for (const relationship of map.relationships) {
    const sourceComponent = componentById.get(relationship.source);
    const targetComponent = componentById.get(relationship.target);
    if (!sourceComponent || !targetComponent) continue;
    const source = detailed
      ? sourceComponent
      : areaById.get(sourceComponent.areaId);
    const target = detailed
      ? targetComponent
      : areaById.get(targetComponent.areaId);
    if (!source || !target || source.id === target.id) continue;
    const key = `${source.id}:${target.id}`;
    const existing = links.get(key);
    const ids = [
      sourceComponent.id,
      targetComponent.id,
      sourceComponent.areaId,
      targetComponent.areaId,
    ];
    links.set(key, {
      source,
      target,
      count: (existing?.count ?? 0) + 1,
      ids: [...(existing?.ids ?? []), ...ids],
    });
  }
  return [...links].map(([id, link]) => {
    if (link.source.x === link.target.x) {
      const down = link.source.y < link.target.y;
      const x = link.source.x + link.source.width / 2;
      const y1 = link.source.y + (down ? link.source.height : 0);
      const y2 = link.target.y + (down ? 0 : link.target.height);
      return { ...link, id, path: `M ${x} ${y1} L ${x} ${y2}` };
    }
    const right = link.source.x <= link.target.x;
    const x1 = link.source.x + (right ? link.source.width : 0);
    const x2 = link.target.x + (right ? 0 : link.target.width);
    const y1 = link.source.y + link.source.height / 2;
    const y2 = link.target.y + link.target.height / 2;
    const bend = Math.max(60, Math.abs(x2 - x1) / 2) * (right ? 1 : -1);
    return {
      ...link,
      id,
      path: `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`,
    };
  });
}
