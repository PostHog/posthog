import { afterEach, beforeAll, describe, expect, it } from "vitest";

import {
  type CreatedResources,
  TEST_ORG_ID,
  TEST_PROJECT_ID,
  cleanupResources,
  createTestClient,
  createTestContext,
  generateUniqueKey,
  parseToolResponse,
  setActiveProjectAndOrg,
  validateEnvironmentVariables,
} from "@/shared/test-utils";
import createDashboardTool from "@/tools/dashboards/create";
import createTextCardTool from "@/tools/dashboards/createTextCard";
import deleteTextCardTool from "@/tools/dashboards/deleteTextCard";
import getDashboardTool from "@/tools/dashboards/get";
import updateTextCardTool from "@/tools/dashboards/updateTextCard";
import type { Context } from "@/tools/types";

describe("Dashboard text cards", { concurrent: false }, () => {
  let context: Context;
  const createdResources: CreatedResources = {
    featureFlags: [],
    insights: [],
    dashboards: [],
    surveys: [],
    actions: [],
    cohorts: [],
  };

  beforeAll(async () => {
    validateEnvironmentVariables();
    const client = createTestClient();
    context = createTestContext(client);
    await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!);
  });

  afterEach(async () => {
    await cleanupResources(context.api, TEST_PROJECT_ID!, createdResources);
  });

  describe("dashboard-text-card-create tool", () => {
    const createDashboard = createDashboardTool();
    const createTextCard = createTextCardTool();

    it("should create a text card on a dashboard", async () => {
      const dashboardResult = await createDashboard.handler(context, {
        data: {
          name: generateUniqueKey("Text Card Dashboard"),
          description: "Dashboard for text card tests",
        },
      });
      const dashboard = parseToolResponse(dashboardResult);
      createdResources.dashboards.push(dashboard.id);

      const result = await createTextCard.handler(context, {
        dashboardId: dashboard.id,
        body: "# Hello World\n\nThis is a **text card**.",
      });
      const textCard = parseToolResponse(result);

      expect(textCard.id).toBeTruthy();
      expect(textCard.text.body).toBe(
        "# Hello World\n\nThis is a **text card**.",
      );
      expect(textCard.dashboard_url).toContain(`/dashboard/${dashboard.id}`);
    });

    it("should create a text card with color", async () => {
      const dashboardResult = await createDashboard.handler(context, {
        data: {
          name: generateUniqueKey("Colored Text Card Dashboard"),
        },
      });
      const dashboard = parseToolResponse(dashboardResult);
      createdResources.dashboards.push(dashboard.id);

      const result = await createTextCard.handler(context, {
        dashboardId: dashboard.id,
        body: "Important note",
        color: "blue",
      });
      const textCard = parseToolResponse(result);

      expect(textCard.id).toBeTruthy();
      expect(textCard.text.body).toBe("Important note");
      expect(textCard.color).toBe("blue");
    });
  });

  describe("dashboard-text-card-update tool", () => {
    const createDashboard = createDashboardTool();
    const createTextCard = createTextCardTool();
    const updateTextCard = updateTextCardTool();

    it("should update a text card body", async () => {
      const dashboardResult = await createDashboard.handler(context, {
        data: {
          name: generateUniqueKey("Update Text Card Dashboard"),
        },
      });
      const dashboard = parseToolResponse(dashboardResult);
      createdResources.dashboards.push(dashboard.id);

      const createResult = await createTextCard.handler(context, {
        dashboardId: dashboard.id,
        body: "Original text",
      });
      const created = parseToolResponse(createResult);

      const updateResult = await updateTextCard.handler(context, {
        dashboardId: dashboard.id,
        tileId: created.id,
        textId: created.text.id,
        body: "Updated text content",
      });
      const updated = parseToolResponse(updateResult);

      expect(updated.id).toBe(created.id);
      expect(updated.text.body).toBe("Updated text content");
    });
  });

  describe("dashboard-text-card-delete tool", () => {
    const createDashboard = createDashboardTool();
    const createTextCard = createTextCardTool();
    const deleteTextCard = deleteTextCardTool();
    const getDashboard = getDashboardTool();

    it("should delete a text card from a dashboard", async () => {
      const dashboardResult = await createDashboard.handler(context, {
        data: {
          name: generateUniqueKey("Delete Text Card Dashboard"),
        },
      });
      const dashboard = parseToolResponse(dashboardResult);
      createdResources.dashboards.push(dashboard.id);

      const createResult = await createTextCard.handler(context, {
        dashboardId: dashboard.id,
        body: "Text to be deleted",
      });
      const created = parseToolResponse(createResult);

      const deleteResult = await deleteTextCard.handler(context, {
        dashboardId: dashboard.id,
        tileId: created.id,
      });
      const deleteResponse = parseToolResponse(deleteResult);

      expect(deleteResponse.success).toBe(true);
      expect(deleteResponse.message).toContain("deleted successfully");

      const getResult = await getDashboard.handler(context, {
        dashboardId: dashboard.id,
      });
      const updatedDashboard = parseToolResponse(getResult);
      const deletedTile = updatedDashboard.tiles?.find(
        (t: any) => t?.id === created.id,
      );
      expect(deletedTile).toBeUndefined();
    });
  });

  describe("text card workflow", () => {
    it("should support full create, update, delete workflow", async () => {
      const createDashboard = createDashboardTool();
      const createTextCard = createTextCardTool();
      const updateTextCard = updateTextCardTool();
      const deleteTextCard = deleteTextCardTool();
      const getDashboard = getDashboardTool();

      const dashboardResult = await createDashboard.handler(context, {
        data: {
          name: generateUniqueKey("Text Card Workflow Dashboard"),
        },
      });
      const dashboard = parseToolResponse(dashboardResult);
      createdResources.dashboards.push(dashboard.id);

      const createResult = await createTextCard.handler(context, {
        dashboardId: dashboard.id,
        body: "# Step 1\n\nInitial content",
      });
      const created = parseToolResponse(createResult);
      expect(created.text.body).toBe("# Step 1\n\nInitial content");

      const updateResult = await updateTextCard.handler(context, {
        dashboardId: dashboard.id,
        tileId: created.id,
        textId: created.text.id,
        body: "# Step 2\n\nUpdated content",
        color: "green",
      });
      const updated = parseToolResponse(updateResult);
      expect(updated.text.body).toBe("# Step 2\n\nUpdated content");

      const deleteResult = await deleteTextCard.handler(context, {
        dashboardId: dashboard.id,
        tileId: created.id,
      });
      const deleted = parseToolResponse(deleteResult);
      expect(deleted.success).toBe(true);

      const getResult = await getDashboard.handler(context, {
        dashboardId: dashboard.id,
      });
      const finalDashboard = parseToolResponse(getResult);
      const remainingTextTiles = finalDashboard.tiles?.filter(
        (t: any) => t?.text && t.id === created.id,
      );
      expect(remainingTextTiles?.length ?? 0).toBe(0);
    });
  });
});
