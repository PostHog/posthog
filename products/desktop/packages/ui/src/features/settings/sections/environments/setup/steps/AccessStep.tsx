import type { EnvironmentSetupPlan } from "@posthog/core/settings/environmentSetup";
import { validateDomains } from "@posthog/core/settings/environmentSetup";
import { Checkbox, Label, Text, Textarea } from "@posthog/quill";
import { NetworkAccessSelect } from "@posthog/ui/features/settings/sections/environments/NetworkAccessSelect";
import { StepBody } from "@posthog/ui/features/settings/sections/environments/setup/StepBody";
import { EnvVarRows } from "@posthog/ui/features/settings/sections/environments/setup/steps/EnvVarRows";
import { useId } from "react";

interface AccessStepProps {
  plan: EnvironmentSetupPlan;
  onChange: (plan: EnvironmentSetupPlan) => void;
  /** True when the environment already holds variables that are not shown back. */
  variablesAlreadySet?: boolean;
}

/** What the sandbox may reach, and what it gets in its shell. */
export function AccessStep({
  plan,
  onChange,
  variablesAlreadySet = false,
}: AccessStepProps) {
  const defaultsId = useId();
  const domainsId = useId();
  const domains = validateDomains(plan.allowedDomainsText);

  return (
    <StepBody
      title="Access"
      description="Which hosts sessions may reach, and the values they get before the agent runs."
    >
      <div className="flex max-w-[520px] flex-col gap-2">
        <Label className="font-medium text-[12.5px]">Network access</Label>
        <NetworkAccessSelect
          value={plan.networkAccessLevel}
          onChange={(networkAccessLevel) =>
            onChange({ ...plan, networkAccessLevel })
          }
        />
      </div>

      {plan.networkAccessLevel === "custom" && (
        <div className="flex flex-col gap-2">
          <Label htmlFor={domainsId} className="font-medium text-[12.5px]">
            Allowed domains
          </Label>
          <Textarea
            id={domainsId}
            rows={4}
            className="max-w-[520px] font-mono text-[12px]"
            value={plan.allowedDomainsText}
            placeholder={"github.com\n*.example.com"}
            data-attr="environment-setup-domains"
            onChange={(event) =>
              onChange({ ...plan, allowedDomainsText: event.target.value })
            }
          />
          <Text className="max-w-[56ch] text-(--gray-10) text-[11.5px] leading-snug">
            One domain per line, no scheme or path. Use * as a wildcard, e.g.
            *.example.com covers every subdomain. Requests anywhere else are
            blocked.
          </Text>
          {domains.errors.map((error) => (
            <Text key={error} className="text-(--amber-11) text-[11.5px]">
              {error}
            </Text>
          ))}
          <label
            htmlFor={defaultsId}
            className="flex w-fit cursor-pointer items-start gap-2"
          >
            <Checkbox
              id={defaultsId}
              className="mt-0.5"
              checked={plan.includeDefaultDomains}
              data-attr="environment-setup-default-domains"
              onCheckedChange={(checked) =>
                onChange({ ...plan, includeDefaultDomains: checked === true })
              }
            />
            <Text className="max-w-[52ch] text-(--gray-11) text-[11.5px] leading-snug">
              Also allow the built-in package managers and source hosts.
              Recommended unless you mean to block them.
            </Text>
          </label>
        </div>
      )}

      <div className="flex flex-col gap-2 border-(--gray-4) border-t border-dashed pt-4">
        <Label className="font-medium text-[12.5px]">
          Environment variables
        </Label>
        <Text className="max-w-[56ch] text-(--gray-10) text-[11.5px] leading-snug">
          {variablesAlreadySet
            ? "Variables are set. They are encrypted and never shown back, so adding any here replaces the whole set, and leaving this empty keeps them."
            : "The API keys or tokens the agent needs. They are encrypted, and never shown back once saved."}
        </Text>
        <EnvVarRows
          rows={plan.envVars}
          onChange={(envVars) => onChange({ ...plan, envVars })}
        />
      </div>
    </StepBody>
  );
}
