import { formatUsd } from "@posthog/core/billing/spendAnalysisFormat";
import {
  hasAnySpendLimit,
  projectedMonthUsd,
  type SpendLimitLevel,
  type SpendLimitPeriod,
  type SpendLimits,
  suggestedSpendLimits,
  utcDayIso,
} from "@posthog/core/billing/spendLimits";
import {
  Button,
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
  Switch,
  Text,
} from "@posthog/quill";
import {
  type SpendSnapshot,
  useSpendTotals,
} from "@posthog/ui/features/billing/useSpendTotals";
import { SettingsSubsection } from "@posthog/ui/features/settings/components/SettingsSubsection";
import {
  clampSpendLine,
  SpendLimitSlider,
  sliderTone,
} from "@posthog/ui/features/settings/sections/SpendLimitSlider";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useId, useState } from "react";

const LIMIT_KEYS: Record<
  SpendLimitPeriod,
  Record<SpendLimitLevel, keyof SpendLimits>
> = {
  day: { warn: "dailyWarnUsd", stop: "dailyStopUsd" },
  month: { warn: "monthlyWarnUsd", stop: "monthlyStopUsd" },
};

function fieldValue(limitUsd: number | null): string {
  return typeof limitUsd === "number" && Number.isFinite(limitUsd)
    ? limitUsd.toLocaleString("en-US")
    : "";
}

/** Empty clears the line; otherwise a positive dollar amount, else no change. */
export function parseSpendLimitField(
  raw: string,
): { ok: true; value: number | null } | { ok: false } {
  const trimmed = raw.trim().replace(/[$,]/g, "");
  if (trimmed === "") return { ok: true, value: null };
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed <= 0) return { ok: false };
  return { ok: true, value: Math.round(parsed * 100) / 100 };
}

export function SpendLimitsSettings() {
  const spendLimits = useSettingsStore((state) => state.spendLimits);
  const setSpendLimits = useSettingsStore((state) => state.setSpendLimits);
  const warnOnModelSwitch = useSettingsStore(
    (state) => state.warnOnMidSessionModelSwitch,
  );
  const setWarnOnModelSwitch = useSettingsStore(
    (state) => state.setWarnOnMidSessionModelSwitch,
  );
  const totals = useSpendTotals();

  return (
    <SpendLimitsSettingsView
      spendLimits={spendLimits}
      totals={totals}
      onCommit={setSpendLimits}
      warnOnModelSwitch={warnOnModelSwitch}
      onWarnOnModelSwitchChange={setWarnOnModelSwitch}
    />
  );
}

interface SpendLimitsSettingsViewProps {
  spendLimits: SpendLimits;
  /** Live spend for the sliders; null renders them without fill or marker. */
  totals: SpendSnapshot | null;
  onCommit: (limits: Partial<SpendLimits>) => void;
  warnOnModelSwitch: boolean;
  onWarnOnModelSwitchChange: (enabled: boolean) => void;
}

export function SpendLimitsSettingsView({
  spendLimits,
  totals,
  onCommit,
  warnOnModelSwitch,
  onWarnOnModelSwitchChange,
}: SpendLimitsSettingsViewProps) {
  const todayIso = utcDayIso();
  const avgUsd = totals && totals.avgDailyUsd > 0 ? totals.avgDailyUsd : null;
  const projectedUsd =
    avgUsd !== null ? projectedMonthUsd(avgUsd, todayIso) : null;
  const suggestion =
    avgUsd !== null && !hasAnySpendLimit(spendLimits)
      ? suggestedSpendLimits(avgUsd, todayIso)
      : null;

  return (
    <SettingsSubsection
      title="Spend limits"
      description="Draw a warning line and a stop line on your spend in this app. The warning only notifies you. The stop pauses new agent messages until you raise or clear it."
    >
      {suggestion && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-(--radius-3) border border-(--gray-4) border-dashed bg-(--gray-2) px-4 py-3">
          <Text className="text-(--gray-11) text-[12.5px]">
            You average{" "}
            <span className="font-medium text-(--gray-12) tabular-nums">
              {formatUsd(avgUsd ?? 0)}
            </span>
            /day, on pace for about{" "}
            <span className="font-medium text-(--gray-12) tabular-nums">
              {formatUsd(projectedUsd ?? 0)}
            </span>{" "}
            this month. Start with lines just above that and tighten later.
          </Text>
          <Button
            variant="outline"
            size="sm"
            data-attr="spend-limits-use-suggestion"
            onClick={() => onCommit(suggestion)}
          >
            Use suggested lines
          </Button>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <SpendPeriodCard
          period="day"
          title="Daily"
          soFarLabel="today"
          spentUsd={totals?.todayUsd ?? null}
          markerUsd={avgUsd}
          markerTitle={
            avgUsd !== null
              ? `Average per day over the last 30 days · ${formatUsd(avgUsd)}`
              : undefined
          }
          detail={avgUsd !== null ? `avg ${formatUsd(avgUsd)}/day` : undefined}
          limits={spendLimits}
          onCommit={onCommit}
        />
        <SpendPeriodCard
          period="month"
          title="Monthly"
          soFarLabel="this month"
          spentUsd={totals?.monthUsd ?? null}
          markerUsd={projectedUsd}
          markerTitle={
            projectedUsd !== null
              ? `Projected month total at your average pace · about ${formatUsd(projectedUsd)}`
              : undefined
          }
          detail={
            projectedUsd !== null
              ? `on pace for ≈${formatUsd(projectedUsd)}`
              : undefined
          }
          limits={spendLimits}
          onCommit={onCommit}
        />
      </div>
      <Text className="text-(--gray-10) text-[12px]">
        Leave a field empty to turn that line off. Spend data can lag 15 to 20
        minutes.
      </Text>
      <div className="flex items-center justify-between gap-4 border-(--gray-4) border-t border-dashed pt-4">
        <span className="flex flex-col gap-0.5">
          <Text className="text-(--gray-12) text-[13px]">
            Warn before a mid-session model switch
          </Text>
          <Text className="text-(--gray-11) text-[12px]">
            Switching models mid-session reprocesses the conversation instead of
            reading it from cache.
          </Text>
        </span>
        <Switch
          checked={warnOnModelSwitch}
          onCheckedChange={onWarnOnModelSwitchChange}
          aria-label="Warn before a mid-session model switch"
          data-attr="spend-limits-model-switch-warning-toggle"
        />
      </div>
    </SettingsSubsection>
  );
}

function SpendPeriodCard({
  period,
  title,
  soFarLabel,
  spentUsd,
  markerUsd,
  markerTitle,
  detail,
  limits,
  onCommit,
}: {
  period: SpendLimitPeriod;
  title: string;
  soFarLabel: string;
  spentUsd: number | null;
  markerUsd: number | null;
  markerTitle?: string;
  detail?: string;
  limits: SpendLimits;
  onCommit: (limits: Partial<SpendLimits>) => void;
}) {
  const warnKey = LIMIT_KEYS[period].warn;
  const stopKey = LIMIT_KEYS[period].stop;
  const warnUsd = limits[warnKey];
  const stopUsd = limits[stopKey];
  const tone = sliderTone(warnUsd, stopUsd, spentUsd ?? 0);

  const commitLine = (level: SpendLimitLevel, value: number | null) => {
    const other = level === "warn" ? stopUsd : warnUsd;
    onCommit({
      [LIMIT_KEYS[period][level]]:
        value === null ? null : clampSpendLine(level, value, other),
    });
  };

  return (
    <div className="flex flex-col gap-2.5 rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid) p-4">
      <div className="flex items-baseline justify-between gap-2">
        <span className="flex items-center gap-2">
          <Text className="font-medium text-(--gray-12) text-[13px]">
            {title}
          </Text>
          {tone !== "ok" && (
            <span
              className={`rounded-full px-1.5 py-0.5 font-medium text-[10px] leading-none ${
                tone === "stop"
                  ? "bg-(--red-a3) text-(--red-11)"
                  : "bg-(--amber-a3) text-(--amber-11)"
              }`}
            >
              {tone === "stop" ? "Stopped" : "Past warning"}
            </span>
          )}
        </span>
        {spentUsd !== null && (
          <span className="flex flex-col items-end gap-0.5 text-right">
            <Text className="text-(--gray-10) text-[12px] leading-none">
              <span className="font-medium text-(--gray-12) tabular-nums">
                {formatUsd(spentUsd)}
              </span>{" "}
              {soFarLabel}
            </Text>
            {detail && (
              <Text className="text-(--gray-9) text-[11px] leading-none">
                {detail}
              </Text>
            )}
          </span>
        )}
      </div>
      <SpendLimitSlider
        warnUsd={warnUsd}
        stopUsd={stopUsd}
        spentUsd={spentUsd ?? 0}
        markerUsd={markerUsd}
        markerTitle={markerTitle}
        periodLabel={title}
        onCommit={commitLine}
      />
      <div className="flex items-center gap-3">
        <SpendLimitField
          period={period}
          level="warn"
          limitUsd={warnUsd}
          onCommit={(value) => commitLine("warn", value)}
        />
        <SpendLimitField
          period={period}
          level="stop"
          limitUsd={stopUsd}
          onCommit={(value) => commitLine("stop", value)}
        />
      </div>
    </div>
  );
}

function SpendLimitField({
  period,
  level,
  limitUsd,
  onCommit,
}: {
  period: SpendLimitPeriod;
  level: SpendLimitLevel;
  limitUsd: number | null;
  onCommit: (value: number | null) => void;
}) {
  const [draft, setDraft] = useState(fieldValue(limitUsd));
  const [synced, setSynced] = useState(limitUsd);

  // Re-sync when another surface changes the stored value, without an effect,
  // so an in-progress edit in this field is never clobbered mid-keystroke.
  if (limitUsd !== synced) {
    setSynced(limitUsd);
    setDraft(fieldValue(limitUsd));
  }

  const commit = () => {
    const parsed = parseSpendLimitField(draft);
    if (!parsed.ok) {
      setDraft(fieldValue(limitUsd));
      return;
    }
    setDraft(fieldValue(parsed.value));
    if (parsed.value !== limitUsd) onCommit(parsed.value);
  };

  const label = level === "warn" ? "Warning" : "Stop";
  const swatchClass =
    level === "warn" ? "border-(--amber-9)" : "border-(--red-9)";
  const inputId = useId();

  return (
    <div className="flex flex-1 items-center gap-2">
      <label
        htmlFor={inputId}
        className="flex shrink-0 items-center gap-1.5 pl-0.5"
      >
        {/* Dashed swatch matching the chart's reference lines. */}
        <span
          className={`w-3 border-t-2 border-dashed ${swatchClass}`}
          aria-hidden="true"
        />
        <Text className="text-(--gray-11) text-[12px]">{label}</Text>
      </label>
      <InputGroup className="h-7 flex-1">
        <InputGroupAddon>
          <InputGroupText className="text-[12px]">$</InputGroupText>
        </InputGroupAddon>
        <InputGroupInput
          id={inputId}
          className="text-[12.5px]"
          inputMode="decimal"
          placeholder="Off"
          value={draft}
          aria-label={`${period === "day" ? "Daily" : "Monthly"} ${label.toLowerCase()} line in dollars`}
          data-attr={`spend-limit-${period}-${level}-input`}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
        />
      </InputGroup>
    </div>
  );
}
