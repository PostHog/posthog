export const selectClass =
  "w-full rounded-(--radius-2) border border-border bg-card px-2 py-1 text-[12px] text-foreground outline-none";

export const eventField = `<Field>
  <FieldLabel>Event</FieldLabel>
  <select
    aria-label="Event"
    value={settings.event}
    onChange={(change) => setSettings({ event: change.target.value })}
    className={SELECT_CLASS}
  >
    {events.names.indexOf(settings.event) === -1 ? (
      <option value={settings.event}>{settings.event}</option>
    ) : null}
    {events.names.map((name) => (
      <option key={name} value={name}>
        {name}
      </option>
    ))}
  </select>
</Field>`;

export const labelField = `<Field>
  <FieldLabel>Label</FieldLabel>
  <Input
    value={settings.label}
    className="h-7 text-[13px]"
    onChange={(change) => setSettings({ label: change.target.value })}
  />
</Field>`;

export const chartStates = `{result.loading ? <Skeleton className="h-full w-full" /> : null}
{result.error ? (
  <div className="flex flex-col items-start gap-2">
    <p className="text-xs text-destructive">This chart did not load.</p>
    <Button variant="outline" size="sm" onClick={result.retry}>
      Try again
    </Button>
  </div>
) : null}
{empty ? (
  <div className="flex h-full items-center justify-center">
    <p className="text-[13px] text-muted-foreground">
      No events in this date range.
    </p>
  </div>
) : null}`;

export function chartTooltip(label: string): string {
  return `function ChartTooltip({ active, payload, label, unit }) {
  if (!active || !payload || payload.length === 0) {
    return null;
  }
  return (
    <div className="rounded-(--radius-2) border border-border bg-popover px-2.5 py-1.5 shadow-md">
      <p className="max-w-56 truncate text-[11px] text-muted-foreground">
        {${label}}
      </p>
      <p className="font-medium text-[13px] tabular-nums">
        {Number(payload[0].value).toLocaleString()} {unit}
      </p>
    </div>
  );
}`;
}
