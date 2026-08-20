import { ArrowSquareOut } from "@phosphor-icons/react";
import type { TaskRunPreferences } from "@posthog/api-client/posthog-client";
import { buildPostHogUrl } from "@posthog/core/settings/posthogUrl";
import { Button } from "@posthog/quill";
import { type Adapter, formatModelId } from "@posthog/shared";
import { EFFORT_LEVEL_LABELS } from "@posthog/shared/domain-types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { ReasoningLevelSelector } from "@posthog/ui/features/sessions/components/ReasoningLevelSelector";
import {
  SettingsCard,
  SettingsCardRow,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { useTaskAgentDefaults } from "@posthog/ui/features/settings/hooks/useTaskAgentDefaults";
import { usePreviewConfig } from "@posthog/ui/features/task-detail/hooks/usePreviewConfig";
import { Text } from "@radix-ui/themes";
import { useEffect, useRef, useState } from "react";

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

/**
 * The composer's own picker, wired to the stored preference instead of a run's config.
 *
 * With nothing stored it shows the inherited project default behind a "Default ·"
 * prefix, so what your runs will use is visible without reading as a pick you made.
 */
function MyDefaultPicker({
  preferences,
  inherited,
  disabled,
  onSave,
}: {
  preferences: TaskRunPreferences;
  inherited: TaskRunPreferences;
  disabled: boolean;
  onSave: (next: TaskRunPreferences) => void;
}) {
  const isInherited = !preferences.model;
  const shown = isInherited ? inherited : preferences;
  const storedAdapter: Adapter =
    shown.runtime_adapter === "codex" ? "codex" : "claude";
  // A harness choice lives here until a model pick on it completes the triple.
  // Saving an all-null pair on the switch would both clear an existing personal
  // default and flip `shown` back to the inherited row, snapping the control
  // to the old harness under the cursor.
  const [pendingAdapter, setPendingAdapter] = useState<Adapter | null>(null);
  const adapter = pendingAdapter ?? storedAdapter;
  useEffect(() => {
    if (pendingAdapter && storedAdapter === pendingAdapter) {
      setPendingAdapter(null);
    }
  }, [pendingAdapter, storedAdapter]);
  const { modelOption, thoughtOption, isLoading, setConfigOption } =
    usePreviewConfig(adapter);

  const anchorRef = useRef<HTMLDivElement | null>(null);

  // Reflect the stored triple into the fetched options, so the pill names the preference
  // rather than whatever the last preview session happened to select.
  const seeded = useRef<string | null>(null);
  const seedKey = `${adapter}:${shown.model ?? ""}:${shown.reasoning_effort ?? ""}`;
  useEffect(() => {
    if (isLoading || seeded.current === seedKey) return;
    // The stored triple belongs to another harness while a switch is pending;
    // seeding its model into this harness's options would show a phantom pick.
    if (pendingAdapter) return;
    seeded.current = seedKey;
    if (shown.model && modelOption) {
      setConfigOption(modelOption.id, shown.model);
    }
    if (shown.reasoning_effort && thoughtOption) {
      setConfigOption(thoughtOption.id, shown.reasoning_effort);
    }
  }, [
    isLoading,
    seedKey,
    pendingAdapter,
    modelOption,
    thoughtOption,
    setConfigOption,
    shown.model,
    shown.reasoning_effort,
  ]);

  const handleModelChange = (model: string) => {
    if (modelOption) setConfigOption(modelOption.id, model);
    // The effort belongs to the model it was chosen against, so a model switch drops it
    // rather than storing one the new model may not support.
    onSave({ runtime_adapter: adapter, model, reasoning_effort: null });
  };

  const handleEffortChange = (effort: string) => {
    if (thoughtOption) setConfigOption(thoughtOption.id, effort);
    // An effort alone is not a preference: it needs the model it was judged
    // against. Read that from the harness's seated option, not the stored
    // triple — mid-switch shown.model still names the previous harness's model,
    // and pairing it with the new adapter saves a preference no surface applies.
    const model =
      modelOption?.type === "select" ? modelOption.currentValue : undefined;
    if (!model) return;
    onSave({
      runtime_adapter: adapter,
      model,
      reasoning_effort: effort || null,
    });
  };

  return (
    // The popup takes its position and width from its anchor. The trigger is a poor one
    // here: this row right-aligns its control, so the button's left edge slides as the
    // label under the cursor changes, and dragging the slider walks the popup with it.
    // This wrapper is a fixed size in a fixed place, so the popup holds still.
    <div ref={anchorRef} className="flex w-[280px] justify-end">
      <ReasoningLevelSelector
        modelOption={modelOption}
        thoughtOption={thoughtOption}
        adapter={adapter}
        anchor={anchorRef}
        // Mid-switch the pill shows the new harness's own default, which is a
        // browse, not the inherited project default — no "Default ·" marker.
        isDefaultSelection={isInherited && !pendingAdapter}
        onModelChange={handleModelChange}
        onChange={handleEffortChange}
        // A slider notch changes model and effort at once. Save them as one
        // preference so the effort can't land on the previously-shown model.
        onNotchSelect={({ model, effort }) => {
          if (modelOption) setConfigOption(modelOption.id, model);
          if (thoughtOption) setConfigOption(thoughtOption.id, effort);
          onSave({
            runtime_adapter: adapter,
            model,
            reasoning_effort: effort || null,
          });
        }}
        onAdapterChange={(next) => {
          // Nothing is saved yet: the next model pick on this harness supplies
          // the pair and carries the adapter with it.
          seeded.current = null;
          setPendingAdapter(next);
        }}
        onConfigOptionChange={(configId, value) => {
          if (modelOption && configId === modelOption.id) {
            handleModelChange(value);
          } else if (thoughtOption && configId === thoughtOption.id) {
            handleEffortChange(value);
          }
        }}
        disabled={disabled}
        isLoading={isLoading}
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
  const currentProjectId = useAuthStateValue((state) => state.currentProjectId);
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

  // The section is per-environment, so the link must name the desktop app's own
  // project — otherwise the web app fills in the browser's active project, which
  // can be a different one, and Manage edits the wrong project's default.
  const settingsUrl = currentProjectId
    ? buildPostHogUrl(
        `/project/${currentProjectId}${POSTHOG_SETTINGS_PATH}`,
        cloudRegion,
      )
    : null;

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
          {/* Deliberately not disabled while saving: the write is debounced and the pick
              already shows, so toggling the control would just make it blink. */}
          <MyDefaultPicker
            preferences={myPreferences}
            inherited={teamPreferences}
            disabled={isLoading}
            onSave={save}
          />
        </SettingsCardRow>

        <SettingsCardRow
          label="Reset my default"
          // Deliberately one fixed sentence: swapping it for a state-dependent one
          // resizes the row on every save, which reads as a flicker.
          description="Clears your own default so the project default applies again."
        >
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!myPreferences.model || isSaving}
            onClick={reset}
          >
            {INHERIT_PROJECT_DEFAULT}
          </Button>
        </SettingsCardRow>
      </SettingsCard>

      {/* Height is reserved rather than left to the text: this line's length changes on
          every save, and letting it reflow between one and two lines shifts the card
          above it each time. */}
      <div className="min-h-10">
        <Text className="text-(--gray-11) text-sm">
          {isLoading
            ? ""
            : resolved.model
              ? `Runs you start without picking a model use ${describe(resolved, "")}, from ${
                  resolved.source === "user"
                    ? "your default"
                    : "the project default"
                }.`
              : "No default is set — runs use each surface's built-in model."}
        </Text>
      </div>
    </div>
  );
}
