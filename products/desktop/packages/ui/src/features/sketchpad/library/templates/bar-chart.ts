import {
  chartStates,
  chartTooltip,
  eventField,
  labelField,
  selectClass,
} from "./chartParts";

export const barChartCode = `import {
  formatCompact,
  hogqlString,
  useDateRange,
  useEventNames,
  useFragmentSettings,
  useHogQL,
} from "@posthog/canvas-sdk";
import {
  Button,
  Field,
  FieldLabel,
  Input,
  Skeleton,
} from "@posthog/quill";
import { SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const DEFAULTS = {
  label: "Top pages",
  event: "$pageview",
  property: "$pathname",
  limit: 8,
};

const COMMON_PROPERTIES = [
  "$pathname",
  "$current_url",
  "$browser",
  "$os",
  "$device_type",
  "$referring_domain",
  "$geoip_country_name",
];

const SELECT_CLASS =
  "${selectClass}";

const LIMITS = [5, 8, 10, 20];

function shorten(name) {
  if (name.length <= 17) {
    return name;
  }
  return name.slice(0, 16) + "…";
}

${chartTooltip("label")}

export default function BreakdownBarChart({ fragmentId }) {
  const [settings, setSettings] = useFragmentSettings(fragmentId, DEFAULTS);
  const [open, setOpen] = useState(false);
  const range = useDateRange(fragmentId);
  const events = useEventNames();
  const limit = Number(settings.limit) || DEFAULTS.limit;
  const result = useHogQL(
    "SELECT properties[" +
      hogqlString(settings.property) +
      "] AS name, count() AS value FROM events WHERE event = " +
      hogqlString(settings.event) +
      " AND timestamp >= " +
      range.since +
      " AND timestamp < now() GROUP BY name ORDER BY value DESC LIMIT " +
      limit,
  );
  const rows = result.rows.map((row) => ({
    name: String(row[0] ?? "") || "(not set)",
    value: Number(row[1] ?? 0),
  }));
  const empty = !result.loading && !result.error && rows.length === 0;

  return (
    <div className="group/bars flex h-full flex-col p-4">
      <div className="flex items-baseline justify-between gap-3 pb-3">
        <p className="truncate text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
          {settings.label}
        </p>
        <button
          type="button"
          aria-label="Settings"
          className={
            open
              ? "shrink-0 rounded p-1 text-foreground"
              : "shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground focus-visible:opacity-100 group-hover/bars:opacity-100"
          }
          onClick={() => setOpen((isOpen) => !isOpen)}
        >
          <SlidersHorizontal size={13} />
        </button>
      </div>

      {open ? (
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto">
          ${eventField}
          <div className="flex gap-2">
            <Field className="min-w-0 flex-1">
              <FieldLabel>Break down by</FieldLabel>
              <Input
                value={settings.property}
                className="h-7 text-[13px]"
                onChange={(change) =>
                  setSettings({ property: change.target.value })
                }
              />
            </Field>
            <Field className="w-24 shrink-0">
              <FieldLabel>Bars</FieldLabel>
              <select
                aria-label="Bars"
                value={String(limit)}
                onChange={(change) => setSettings({ limit: Number(change.target.value) })}
                className={SELECT_CLASS}
              >
                {LIMITS.map((item) => (
                  <option key={item} value={String(item)}>
                    {item}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="flex flex-wrap gap-1">
            {COMMON_PROPERTIES.map((name) => (
              <button
                key={name}
                type="button"
                className={
                  name === settings.property
                    ? "rounded-full bg-primary px-2 py-0.5 text-[11px] text-primary-foreground"
                    : "rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
                }
                onClick={() => setSettings({ property: name })}
              >
                {name}
              </button>
            ))}
          </div>
          ${labelField}
        </div>
      ) : (
        <div className="min-h-0 flex-1">
          ${chartStates}
          {!result.loading && !result.error && rows.length > 0 ? (
            <ResponsiveContainer height="100%" width="100%">
              <BarChart
                data={rows}
                layout="vertical"
                barCategoryGap="28%"
                margin={{ top: 0, right: 12, bottom: 0, left: 0 }}
              >
                <CartesianGrid
                  horizontal={false}
                  stroke="var(--border)"
                  strokeDasharray="2 4"
                />
                <XAxis
                  type="number"
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  tickFormatter={formatCompact}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={112}
                  axisLine={false}
                  tickLine={false}
                  tickMargin={8}
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  tickFormatter={shorten}
                />
                <Tooltip
                  cursor={{ fill: "var(--muted)", opacity: 0.4 }}
                  content={<ChartTooltip unit="events" />}
                />
                <Bar
                  dataKey="value"
                  fill="var(--primary)"
                  radius={[0, 4, 4, 0]}
                  maxBarSize={18}
                />
              </BarChart>
            </ResponsiveContainer>
          ) : null}
        </div>
      )}
    </div>
  );
}
`;
