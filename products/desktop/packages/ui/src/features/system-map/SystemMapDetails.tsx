import type {
  SystemMap,
  SystemMapComponent,
  SystemMapEvidence,
} from "@posthog/core/system-map/schemas";
import { Button } from "@posthog/quill";
import type { ReactElement } from "react";

export function Evidence({
  items,
}: {
  items: SystemMapEvidence[];
}): ReactElement {
  return (
    <ul className="space-y-3">
      {items.map((item, index) => (
        <li key={`${item.path}:${item.line}:${index}`}>
          <code className="break-all text-primary">
            {item.path}:{item.line}
          </code>
          <p className="mt-1 text-muted-foreground">{item.note}</p>
        </li>
      ))}
    </ul>
  );
}

const coverageLabels = {
  reviewed: "Reviewed",
  partial: "Partly reviewed",
  not_reviewed: "Not reviewed",
};

export function ScanCoverage({
  map,
  onSelect,
}: {
  map: SystemMap;
  onSelect: (id: string, kind: "component") => void;
}): ReactElement {
  const components = new Map(
    map.areas.flatMap((area) =>
      area.components.map((component) => [component.id, component.name]),
    ),
  );
  const partial = map.coverage.filter((scope) => scope.status === "partial");
  const unreviewed = map.coverage.filter(
    (scope) => scope.status === "not_reviewed",
  );
  return (
    <details className="space-y-3">
      <summary className="cursor-pointer font-medium">
        Scan coverage
        <span className="mt-1 block font-normal text-muted-foreground">
          {map.coverage.length} source scopes · {partial.length} partly reviewed
          {" · "}
          {unreviewed.length} not reviewed
        </span>
      </summary>
      <p className="text-muted-foreground">
        The agent reports what it read. This list does not confirm that all
        source files were found or checked.
      </p>
      <ul className="space-y-4">
        {map.coverage.map((scope) => (
          <li key={scope.path} className="space-y-2">
            <div>
              <code className="break-all">{scope.path}</code>
              <p className="text-muted-foreground">
                {coverageLabels[scope.status]}
              </p>
            </div>
            <p>{scope.summary}</p>
            {scope.componentIds.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {scope.componentIds.map((id) => (
                  <Button
                    key={id}
                    size="sm"
                    variant="outline"
                    className="max-w-full"
                    onClick={() => onSelect(id, "component")}
                  >
                    <span className="truncate">{components.get(id)}</span>
                  </Button>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

const operationLabels = {
  query: "Reads state",
  command: "Changes state or causes an external effect",
  unknown: "Effect not established",
};

export function PublicOperations({
  component,
}: {
  component: SystemMapComponent;
}): ReactElement {
  return (
    <section>
      <h3 className="mb-2 font-medium">Public operations</h3>
      {component.operations.length === 0 ? (
        <p className="text-muted-foreground">
          No public operations were identified in the inspected source.
        </p>
      ) : (
        <ul className="space-y-4">
          {component.operations.map((operation, index) => (
            <li key={`${operation.name}:${index}`} className="space-y-2">
              <div>
                <h4 className="break-all font-mono">{operation.name}</h4>
                <p className="text-muted-foreground">
                  {operationLabels[operation.kind]}
                </p>
              </div>
              <p>{operation.summary}</p>
              <Evidence items={operation.evidence} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function ConnectionAssumptions({
  assumptions,
}: {
  assumptions: SystemMap["relationships"][number]["assumptions"];
}): ReactElement | null {
  if (assumptions.length === 0) return null;
  return (
    <section className="space-y-2">
      <h4 className="font-medium">Assumptions (not checked)</h4>
      <ul className="space-y-3">
        {assumptions.map((assumption, index) => (
          <li key={`${assumption.summary}:${index}`} className="space-y-2">
            <p>{assumption.summary}</p>
            <Evidence items={assumption.evidence} />
          </li>
        ))}
      </ul>
    </section>
  );
}
