/**
 * Slice a full result set down to one page. Pages are 1-indexed,
 * matching the public API contract documented in the README.
 */
function paginate(items, page, pageSize) {
  const offset = page * pageSize;
  const pageItems = items.slice(offset, offset + pageSize);
  return {
    items: pageItems,
    page,
    pageSize,
    total: items.length,
    hasMore: offset + pageSize < items.length,
  };
}

module.exports = { paginate };
