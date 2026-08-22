import type {
  SpendLimitLevel,
  SpendLimitPeriod,
  SpendLimits,
} from "@posthog/core/billing/spendLimits";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
  Switch,
  Text,
} from "@posthog/quill";
import { SettingsSubsection } from "@posthog/ui/features/settings/components/SettingsSubsection";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useId, useState } from "react";

const LIMIT_KEYS: Record<
  SpendLimitPeriod,
  Record<SpendLimitLevel, keyof SpendLimits>
> = {
  day: { warn: "dailyWarnUsd", alert: "dailyAlertUsd" },
  month: { warn: "monthlyWarnUsd", alert: "monthlyAlertUsd" },
};

function fieldValue(limitUsd: number | null): string {
  return limitUsd === null ? "" : String(limitUsd);
}

/** Empty clears the line; otherwise a positive dollar amount, else no change. */
export function parseSpendLimitField(
  raw: string,
): { ok: true; value: number | null } | { ok: false } {
  const trimmed = raw.trim().replace(/^\$/, "");
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

  return (
    <SettingsSubsection
      title="Spend limits"
      description="Get a notification when your spend in this app passes a line you set. Lines only inform you. Nothing is paused or blocked."
    >
      <div className="flex flex-col gap-3 rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid) p-4">
        <div className="grid gap-6 sm:grid-cols-2">
          <SpendLimitGroup
            period="day"
            title="Daily"
            limits={spendLimits}
            onCommit={setSpendLimits}
          />
          <SpendLimitGroup
            period="month"
            title="Monthly"
            limits={spendLimits}
            onCommit={setSpendLimits}
          />
        </div>
        <Text className="text-(--gray-10) text-[12px]">
          Leave a field empty to turn that line off. Spend data can lag 15 to 20
          minutes.
        </Text>
      </div>
      <div className="flex items-center justify-between gap-4">
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
          onCheckedChange={setWarnOnModelSwitch}
          aria-label="Warn before a mid-session model switch"
          data-attr="spend-limits-model-switch-warning-toggle"
        />
      </div>
    </SettingsSubsection>
  );
}

function SpendLimitGroup({
  period,
  title,
  limits,
  onCommit,
}: {
  period: SpendLimitPeriod;
  title: string;
  limits: SpendLimits;
  onCommit: (limits: Partial<SpendLimits>) => void;
}) {
  const warnKey = LIMIT_KEYS[period].warn;
  const alertKey = LIMIT_KEYS[period].alert;
  const warnUsd = limits[warnKey];
  const alertUsd = limits[alertKey];
  const misordered =
    warnUsd !== null && alertUsd !== null && warnUsd > alertUsd;

  return (
    <div className="flex flex-col gap-2">
      <Text className="font-medium text-(--gray-12) text-[13px]">{title}</Text>
      <div className="grid grid-cols-2 gap-3">
        <SpendLimitField
          period={period}
          level="warn"
          limitUsd={warnUsd}
          onCommit={(value) => onCommit({ [warnKey]: value })}
        />
        <SpendLimitField
          period={period}
          level="alert"
          limitUsd={alertUsd}
          onCommit={(value) => onCommit({ [alertKey]: value })}
        />
      </div>
      {misordered && (
        <Text className="text-(--amber-11) text-[12px]">
          The warning line is above the alert line.
        </Text>
      )}
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

  const label = level === "warn" ? "Warning" : "Alert";
  const dotClass = level === "warn" ? "bg-(--amber-9)" : "bg-(--red-9)";
  const inputId = useId();

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={inputId} className="flex items-center gap-1.5">
        <span className={`size-2 rounded-full ${dotClass}`} />
        <Text className="text-(--gray-11) text-[12px]">{label}</Text>
      </label>
      <InputGroup>
        <InputGroupAddon>
          <InputGroupText>$</InputGroupText>
        </InputGroupAddon>
        <InputGroupInput
          id={inputId}
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
