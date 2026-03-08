import type { z } from "zod";

import { TextCardUpdateSchema } from "@/schema/tool-inputs";
import type { Context, ToolBase } from "@/tools/types";

const schema = TextCardUpdateSchema;

type Params = z.infer<typeof schema>;

type Result = {
  id: number;
  text: { id: number; body: string };
  dashboard_url: string;
};

export const updateTextCardHandler: ToolBase<
  typeof schema,
  Result
>["handler"] = async (context: Context, params: Params) => {
  const { dashboardId, tileId, textId, body, color } = params;
  const projectId = await context.stateManager.getProjectId();

  const tile: Record<string, unknown> = {
    id: tileId,
    text: { id: textId, body },
  };
  if (color !== undefined) {
    tile.color = color;
  }

  const result = await context.api.dashboards({ projectId }).update({
    dashboardId,
    data: { tiles: [tile] },
  });

  if (!result.success) {
    throw new Error(`Failed to update text card: ${result.error.message}`);
  }

  const updatedTile = result.data.tiles?.find((t: any) => t.id === tileId);

  if (!updatedTile) {
    throw new Error(
      "Text card was updated but could not be found in the response",
    );
  }

  return {
    id: updatedTile.id,
    text: updatedTile.text,
    color: updatedTile.color,
    dashboard_url: `${context.api.getProjectBaseUrl(projectId)}/dashboard/${dashboardId}`,
  };
};

const tool = (): ToolBase<typeof schema, Result> => ({
  name: "dashboard-text-card-update",
  schema,
  handler: updateTextCardHandler,
});

export default tool;
