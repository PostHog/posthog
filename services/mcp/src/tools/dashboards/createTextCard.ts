import type { z } from "zod";

import { TextCardCreateSchema } from "@/schema/tool-inputs";
import type { Context, ToolBase } from "@/tools/types";

const schema = TextCardCreateSchema;

type Params = z.infer<typeof schema>;

type Result = {
  id: number;
  text: { id: number; body: string };
  dashboard_url: string;
};

export const createTextCardHandler: ToolBase<
  typeof schema,
  Result
>["handler"] = async (context: Context, params: Params) => {
  const { dashboardId, body, color } = params;
  const projectId = await context.stateManager.getProjectId();

  const tile: Record<string, unknown> = {
    text: { body },
  };
  if (color) {
    tile.color = color;
  }

  const result = await context.api.dashboards({ projectId }).update({
    dashboardId,
    data: { tiles: [tile] },
  });

  if (!result.success) {
    throw new Error(`Failed to create text card: ${result.error.message}`);
  }

  const createdTile = result.data.tiles?.find(
    (t: any) => t.text?.body === body && !t.insight,
  );

  if (!createdTile) {
    throw new Error(
      "Text card was created but could not be found in the response",
    );
  }

  return {
    id: createdTile.id,
    text: createdTile.text,
    color: createdTile.color,
    dashboard_url: `${context.api.getProjectBaseUrl(projectId)}/dashboard/${dashboardId}`,
  };
};

const tool = (): ToolBase<typeof schema, Result> => ({
  name: "dashboard-text-card-create",
  schema,
  handler: createTextCardHandler,
});

export default tool;
