import type { z } from "zod";

import { TextCardDeleteSchema } from "@/schema/tool-inputs";
import type { Context, ToolBase } from "@/tools/types";

const schema = TextCardDeleteSchema;

type Params = z.infer<typeof schema>;

type Result = { success: boolean; message: string; dashboard_url: string };

export const deleteTextCardHandler: ToolBase<
  typeof schema,
  Result
>["handler"] = async (context: Context, params: Params) => {
  const { dashboardId, tileId } = params;
  const projectId = await context.stateManager.getProjectId();

  const result = await context.api.dashboards({ projectId }).update({
    dashboardId,
    data: { tiles: [{ id: tileId, deleted: true }] },
  });

  if (!result.success) {
    throw new Error(`Failed to delete text card: ${result.error.message}`);
  }

  return {
    success: true,
    message: `Text card tile ${tileId} deleted successfully from dashboard ${dashboardId}`,
    dashboard_url: `${context.api.getProjectBaseUrl(projectId)}/dashboard/${dashboardId}`,
  };
};

const tool = (): ToolBase<typeof schema, Result> => ({
  name: "dashboard-text-card-delete",
  schema,
  handler: deleteTextCardHandler,
});

export default tool;
