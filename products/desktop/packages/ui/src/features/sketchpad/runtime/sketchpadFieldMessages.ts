import {
  isField,
  materializeList,
  materializeText,
  SKETCHPAD_FIELD_MARK,
} from "@posthog/shared";

export interface SketchpadTextMessage {
  __text: string;
  ids: string[];
}

export interface SketchpadListMessage {
  __list: { id: string; value: unknown }[];
}

export function fieldMessageValue(value: unknown): unknown {
  if (!isField(value)) return value;
  if (value[SKETCHPAD_FIELD_MARK] === "text") {
    const view = materializeText(value);
    const message: SketchpadTextMessage = { __text: view.text, ids: view.ids };
    return message;
  }
  const message: SketchpadListMessage = { __list: materializeList(value) };
  return message;
}

export function fieldPlainValue(value: unknown): unknown {
  if (!isField(value)) return value;
  if (value[SKETCHPAD_FIELD_MARK] === "text") {
    return materializeText(value).text;
  }
  return materializeList(value).map((row) => row.value);
}
