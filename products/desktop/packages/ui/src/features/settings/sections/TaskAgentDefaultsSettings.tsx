import { ArrowSquareOut } from "@phosphor-icons/react";
import { getReasoningEffortOptions } from "@posthog/agent/adapters/reasoning-effort";
import type { TaskRunPreferences } from "@posthog/api-client/posthog-client";
import { buildPostHogUrl } from "@posthog/core/settings/posthogUrl";
import { flattenConfigValues } from "@posthog/core/task-detail/configOptions";
import { Button } from "@posthog/quill";
import { type Adapter, formatModelId } from "@posthog/shared";
import { EFFORT_LEVEL_LABELS } from "@posthog/shared/domain-types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  SettingsCard,
  SettingsCardRow,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { SettingsSelect } from "@posthog/ui/features/settings/components/SettingsSelect";
import { useTaskAgentDefaults } from "@posthog/ui/features/settings/hooks/useTaskAgentDefaults";
import { usePreviewConfig } from "@posthog/ui/features/task-detail/hooks/usePreviewConfig";
import { Text } from "@radix-ui/themes";
import { useMemo } from "react";

/** The tasks settings page in PostHog, where the project default is set. */
const POSTHOG_SETTINGS_PATH = "/settings/environment-task-agents";

const INHERIT_PROJECT_DEFAULT = "Use project default";

function effortLabel(effort: string): string {
  return (
    EFFORT_LEVEL_LABELS[effort as keyof typeof EFFORT_LEVEL_LABELS] ?? effort
  );
}

/** A stored triple as prose, or a note that the level is unset. */
function describe(preferences: TaskRunPreferences, emptyLabel: string): string {
  if (!preferences.model) return emptyLabel;
  const model = formatModelId(preferences.model);
  return preferences.reasoning_effort
    ? `${model} · ${effortLabel(preferences.reasoning_effort)}`
    : model;
}

interface ModelChoice {
  model: string;
  adapter: Adapter;
}

/**
 * Selects for this user's own default, bound to the stored preference rather than to a
 * live session's config: clearing it has to read as empty here, which a composer picker
 * (which always shows whatever the run would use) can't express.
 */
function MyDefaultPicker({
  preferences,
  disabled,
  onSave,
}: {
  preferences: TaskRunPreferences;
  disabled: boolean;
  onSave: (next: TaskRunPreferences) => void;
}) {
  // Both harnesses, so a Codex default is settable here as readily as a Claude one.
  const claude = usePreviewConfig("claude");
  const codex = usePreviewConfig("codex");

  const choices = useMemo<ModelChoice[]>(() => {
    const collect = (
      option: typeof claude.modelOption,
      adapter: Adapter,
    ): ModelChoice[] =>
      option?.type === "select"
        ? flattenConfigValues(option).map((model) => ({ model, adapter }))
        : [];
    return [
      ...collect(claude.modelOption, "claude"),
      ...collect(codex.modelOption, "codex"),
    ];
  }, [claude.modelOption, codex.modelOption]);

  const selectedAdapter =
    choices.find((c) => c.model === preferences.model)?.adapter ??
    (preferences.runtime_adapter === "codex" ? "codex" : "claude");

  const efforts = preferences.model
    ? (getReasoningEffortOptions(selectedAdapter, preferences.model) ?? [])
    : [];

  return (
    <div className="flex items-center gap-2">
      <SettingsSelect
        ariaLabel="My default model"
        value={preferences.model}
        placeholder={INHERIT_PROJECT_DEFAULT}
        triggerClassName="w-56"
        options={[
          { value: null, label: INHERIT_PROJECT_DEFAULT },
          ...choices.map(({ model }) => ({
            value: model,
            label: formatModelId(model),
          })),
        ]}
        onChange={(model) => {
          if (disabled) return;
          const adapter =
            choices.find((c) => c.model === model)?.adapter ?? selectedAdapter;
          // The effort belongs to the model it was chosen against, so a model switch
          // drops it rather than storing one the new model may not support.
          onSave({
            runtime_adapter: model ? adapter : null,
            model,
            reasoning_effort: null,
          });
        }}
      />
      <SettingsSelect
        ariaLabel="My default reasoning effort"
        value={preferences.reasoning_effort}
        placeholder="Default effort"
        triggerClassName="w-40"
        options={[
          { value: null, label: "Default effort" },
          ...efforts.map((effort) => ({
            value: effort.value,
            label: effort.name || effortLabel(effort.value),
          })),
        ]}
        onChange={(reasoning_effort) => {
          if (disabled || !preferences.model) return;
          onSave({ ...preferences, reasoning_effort });
        }}
      />
    </div>
  );
}

/**
 * What agent runs in this project launch with when nobody picks a model.
 *
 * Both levels are shown because only seeing the resolved answer leaves "why this
 * model" unanswerable. The project default is read-only here: it is admin-gated in
 * PostHog, so this links out rather than offering a control that would be refused.
 */
export function TaskAgentDefaultsSettings() {
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const isAuthenticated = useAuthStateValue(
    (state) => state.status === "authenticated",
  );
  const {
    teamPreferences,
    myPreferences,
    resolved,
    isLoading,
    isSaving,
    save,
    reset,
  } = useTaskAgentDefaults();

  const settingsUrl = buildPostHogUrl(POSTHOG_SETTINGS_PATH, cloudRegion);

  if (!isAuthenticated) {
    return (
      <Text className="text-(--gray-11) text-sm">
        Sign in to PostHog to see the defaults this project runs with.
      </Text>
    );
  }

  return (
    <div className="flex flex-col gap-7">
      <SettingsCard>
        <SettingsCardRow
          label="Project default"
          description="What everyone on this project inherits. Only project admins can change it."
        >
          <div className="flex items-center gap-2">
            <Text className="text-(--gray-11) text-sm">
              {isLoading
                ? "Loading…"
                : describe(teamPreferences, "No project default")}
            </Text>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!settingsUrl}
              onClick={() => {
                if (settingsUrl) window.open(settingsUrl, "_blank");
              }}
            >
              Manage
              <ArrowSquareOut size={12} />
            </Button>
          </div>
        </SettingsCardRow>

        <SettingsCardRow
          label="My default"
          description="Overrides the project default for your own runs, everywhere in PostHog — not just this app."
        >
          <MyDefaultPicker
            preferences={myPreferences}
            disabled={isLoading || isSaving}
            onSave={(next) => void save(next)}
          />
        </SettingsCardRow>

        <SettingsCardRow
          label="Reset my default"
          description={
            myPreferences.model
              ? "Go back to inheriting the project default."
              : "You're already inheriting the project default."
          }
        >
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!myPreferences.model || isSaving}
            onClick={() => void reset()}
          >
            {INHERIT_PROJECT_DEFAULT}
          </Button>
        </SettingsCardRow>
      </SettingsCard>

      <Text className="text-(--gray-11) text-sm">
        {resolved.model
          ? `Runs you start without picking a model use ${describe(resolved, "")}, from ${
              resolved.source === "user"
                ? "your default"
                : "the project default"
            }.`
          : "No default is set — runs use each surface's built-in model."}
      </Text>
    </div>
  );
}
