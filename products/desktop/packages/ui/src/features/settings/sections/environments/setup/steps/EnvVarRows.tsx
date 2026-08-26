import { Plus, X } from "@phosphor-icons/react";
import {
  type EnvVarRow,
  envVarError,
  parseEnvVarText,
} from "@posthog/core/settings/environmentSetup";
import { Button, Input, Text } from "@posthog/quill";
import type { ClipboardEvent } from "react";

interface EnvVarRowsProps {
  rows: readonly EnvVarRow[];
  onChange: (rows: EnvVarRow[]) => void;
}

/**
 * Environment variables as name and value pairs. Pasting a .env file fills the
 * rows out, since that is how people carry these between machines, and the
 * value column masks what it holds because most of them are secrets.
 */
export function EnvVarRows({ rows, onChange }: EnvVarRowsProps) {
  // Random ids, not row-count ones: a count repeats after delete-then-add,
  // and a repeated id makes patch() edit two rows at once.
  const nextId = () => crypto.randomUUID();

  const addRow = () =>
    onChange([...rows, { id: nextId(), key: "", value: "" }]);

  const patch = (id: string, part: Partial<EnvVarRow>) =>
    onChange(rows.map((row) => (row.id === id ? { ...row, ...part } : row)));

  /**
   * A paste that carries variables replaces the row it landed in, so pasting
   * into the first empty row does not leave a blank one behind.
   */
  const handlePaste = (event: ClipboardEvent, row: EnvVarRow) => {
    const text = event.clipboardData.getData("text");
    const parsed = parseEnvVarText(text);
    if (parsed.length === 0) return;
    if (parsed.length === 1 && !text.includes("\n") && row.key.trim() !== "") {
      return;
    }
    event.preventDefault();
    const added = parsed.map((entry) => ({
      id: nextId(),
      ...entry,
    }));
    const isBlank = row.key.trim() === "" && row.value.trim() === "";
    onChange([
      ...rows.filter((current) => current.id !== row.id || !isBlank),
      ...added,
    ]);
  };

  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-start gap-2 rounded-(--radius-3) border border-(--gray-5) border-dashed px-3 py-3">
        <Text className="text-(--gray-11) text-[11.5px]">
          None yet. Add them one at a time, or paste a .env file into the first
          row.
        </Text>
        <Button
          variant="outline"
          size="sm"
          data-attr="environment-setup-add-variable"
          onClick={addRow}
        >
          <Plus size={12} />
          Add a variable
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex max-w-[640px] items-center gap-2">
        <Text className="flex-1 text-(--gray-10) text-[11px]">Name</Text>
        <Text className="flex-1 text-(--gray-10) text-[11px]">Value</Text>
        <span className="w-7 shrink-0" />
      </div>
      {rows.map((row, index) => {
        const error = envVarError(row, rows);
        return (
          <div key={row.id} className="flex flex-col gap-1">
            <div className="flex max-w-[640px] items-center gap-2">
              <Input
                className="h-7 flex-1 font-mono text-[12px]"
                value={row.key}
                placeholder="OPENAI_API_KEY"
                aria-label={`Variable ${index + 1} name`}
                data-attr={`environment-setup-variable-key-${index}`}
                onChange={(event) => patch(row.id, { key: event.target.value })}
                onPaste={(event) => handlePaste(event, row)}
              />
              <Input
                type="password"
                className="h-7 flex-1 font-mono text-[12px]"
                value={row.value}
                placeholder="sk-…"
                aria-label={`Variable ${index + 1} value`}
                data-attr={`environment-setup-variable-value-${index}`}
                onChange={(event) =>
                  patch(row.id, { value: event.target.value })
                }
                onPaste={(event) => handlePaste(event, row)}
              />
              <Button
                variant="link-muted"
                size="sm"
                className="w-7 shrink-0"
                aria-label={`Remove variable ${index + 1}`}
                onClick={() =>
                  onChange(rows.filter((current) => current.id !== row.id))
                }
              >
                <X size={12} />
              </Button>
            </div>
            {error && (
              <Text className="text-(--amber-11) text-[11.5px]">{error}</Text>
            )}
          </div>
        );
      })}
      <div className="flex items-center gap-3">
        <Button
          variant="outline"
          size="sm"
          data-attr="environment-setup-add-variable"
          onClick={addRow}
        >
          <Plus size={12} />
          Add a variable
        </Button>
        <Text className="text-(--gray-10) text-[11.5px]">
          Pasting a .env file fills out the rows.
        </Text>
      </div>
    </div>
  );
}
