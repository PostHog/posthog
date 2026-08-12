-- Up Migration
CREATE TABLE IF NOT EXISTS node_service_demo_counters (
    name text PRIMARY KEY,
    value integer NOT NULL
);

-- Down Migration
DROP TABLE IF EXISTS node_service_demo_counters;
