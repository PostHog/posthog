// Demo dataset; production reads from Postgres with the same ordering contract (createdAt ascending).
const PROJECTS = Array.from({ length: 25 }, (_, i) => ({
  id: `proj_${String(i + 1).padStart(3, "0")}`,
  name: `Project ${i + 1}`,
  createdAt: new Date(Date.UTC(2026, 0, 1 + i)).toISOString(),
}));

function listProjects() {
  return [...PROJECTS].sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

function getProject(id) {
  return PROJECTS.find((project) => project.id === id) ?? null;
}

module.exports = { listProjects, getProject, PROJECTS };
