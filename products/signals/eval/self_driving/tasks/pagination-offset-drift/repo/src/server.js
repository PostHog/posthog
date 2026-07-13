const express = require("express");
const { listProjects, getProject } = require("./projects");
const { paginate } = require("./pagination");
const { parseListParams } = require("./validation");
const analytics = require("./analytics");

const app = express();

app.get("/api/projects", (req, res) => {
  const { page, pageSize } = parseListParams(req.query);
  const result = paginate(listProjects(), page, pageSize);
  analytics.capture(req.headers["x-api-client"] || "anonymous", "projects_listed", {
    page,
    page_size: pageSize,
    returned_count: result.items.length,
    total: result.total,
  });
  res.json(result);
});

app.get("/api/projects/:id", (req, res) => {
  const project = getProject(req.params.id);
  if (!project) return res.status(404).json({ error: "project_not_found" });
  res.json(project);
});

const port = process.env.PORT || 3000;
if (require.main === module) {
  app.listen(port, () => console.log(`acme-projects-api listening on :${port}`));
}

module.exports = app;
