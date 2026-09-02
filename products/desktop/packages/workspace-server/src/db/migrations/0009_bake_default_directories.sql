UPDATE workspaces
SET additional_directories = (
  SELECT json_group_array(path)
  FROM (
    SELECT value AS path FROM json_each(workspaces.additional_directories)
    UNION
    SELECT path FROM default_additional_directories
  )
)
WHERE (SELECT COUNT(*) FROM default_additional_directories) > 0;
