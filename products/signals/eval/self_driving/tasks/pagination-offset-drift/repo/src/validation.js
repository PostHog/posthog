const MAX_PAGE_SIZE = 100;

/** Parse and clamp pagination query params. */
function parseListParams(query = {}) {
  const page = Math.max(1, Number.parseInt(query.page, 10) || 1);
  const pageSize = Math.min(MAX_PAGE_SIZE, Math.max(1, Number.parseInt(query.page_size, 10) || 20));
  return { page, pageSize };
}

module.exports = { parseListParams, MAX_PAGE_SIZE };
