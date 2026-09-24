import { X } from "@phosphor-icons/react";
import type { SystemMap } from "@posthog/core/system-map/schemas";
import { Button } from "@posthog/quill";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import type { ReactElement } from "react";
import {
  ConnectionAssumptions,
  Evidence,
  PublicOperations,
  ScanCoverage,
} from "./SystemMapDetails";

export function SystemMapInspector({
  map,
  selectedId,
  onSelect,
  onClose,
}: {
  map: SystemMap;
  selectedId: string | null;
  onSelect: (id: string, kind: "area" | "component") => void;
  onClose: () => void;
}): ReactElement {
  const components = map.areas.flatMap((area) => area.components);
  const selectedArea = map.areas.find((area) => area.id === selectedId);
  const selectedComponent = components.find(
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
    components.map((component) => [component.id, component.name]),
  );
  return (
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
              onClick={() => onClose()}
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
              Scroll to zoom. Drag to move. Hover or focus a card to trace its
              connections. Select a card to inspect the source.
            </p>
            <div className="space-y-1">
              {map.areas.map((area) => (
                <Button
                  key={area.id}
                  variant="default"
                  size="sm"
                  className="w-full justify-start"
                  onClick={() => onSelect(area.id, "area")}
                >
                  {area.name}
                </Button>
              ))}
            </div>
            <ScanCoverage map={map} onSelect={onSelect} />
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
                  onClick={() => onSelect(component.id, "component")}
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
                        onClick={() => onSelect(link.source, "component")}
                      >
                        {componentNames.get(link.source)}
                      </Button>
                      <span className="text-muted-foreground">
                        → {link.kind} →
                      </span>
                      <Button
                        size="sm"
                        variant="default"
                        onClick={() => onSelect(link.target, "component")}
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
  );
}
