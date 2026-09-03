import { Plus, X } from "@phosphor-icons/react";
import type { SetupLine } from "@posthog/core/settings/environmentSetup";
import { setupCommandError } from "@posthog/core/settings/imageSpec";
import { Button, Input, Text } from "@posthog/quill";

interface SetupCommandListProps {
  lines: readonly SetupLine[];
  onChange: (lines: SetupLine[]) => void;
}

/** The editable list of setup commands, one line each. */
export function SetupCommandList({ lines, onChange }: SetupCommandListProps) {
  return (
    <div className="flex flex-col gap-2">
      {lines.map((line, index) => {
        const error =
          line.value.trim() === "" ? null : setupCommandError(line.value);
        return (
          <div key={line.id} className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <Text className="w-4 shrink-0 text-(--gray-9) text-[11px] tabular-nums">
                {index + 1}
              </Text>
              <Input
                className="h-7 flex-1 font-mono text-[12px]"
                value={line.value}
                placeholder="pnpm install --frozen-lockfile"
                aria-label={`Setup command ${index + 1}`}
                data-attr={`environment-setup-command-${index}`}
                onChange={(event) =>
                  onChange(
                    lines.map((current) =>
                      current.id === line.id
                        ? { ...current, value: event.target.value }
                        : current,
                    ),
                  )
                }
              />
              <Button
                variant="link-muted"
                size="sm"
                aria-label={`Remove setup command ${index + 1}`}
                onClick={() =>
                  onChange(lines.filter((current) => current.id !== line.id))
                }
              >
                <X size={12} />
              </Button>
            </div>
            {error && (
              <Text className="pl-6 text-(--amber-11) text-[11.5px]">
                {error}
              </Text>
            )}
          </div>
        );
      })}
      <div className="flex items-center gap-3">
        <Button
          variant="outline"
          size="sm"
          data-attr="environment-setup-add-command"
          // A random id, not the line count: a count repeats after
          // delete-then-add, and a repeated id makes edits hit two lines.
          onClick={() =>
            onChange([...lines, { id: crypto.randomUUID(), value: "" }])
          }
        >
          <Plus size={12} />
          Add a command
        </Button>
        <Text className="text-(--gray-10) text-[11.5px]">
          One line each. Chain steps with &amp;&amp;.
        </Text>
      </div>
    </div>
  );
}
