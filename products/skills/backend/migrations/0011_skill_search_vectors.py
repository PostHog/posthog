from django.db import migrations

# The search_vector columns stay off the Django models. Every LLMSkill and LLMSkillFile read would
# otherwise load them, including the list paths that defer `body` to keep responses small.
#
# A trigger fills the columns, not application code, because skills are written through many paths
# (create, publish, duplicate, import, community install, the lazy seeders in other products) and
# several use bulk_create or QuerySet.update, which skip save(). A generated column would do the
# same job, but adding a STORED generated column rewrites both tables under an exclusive lock.
#
# to_tsvector raises program_limit_exceeded when the vector passes 1MB, which text of mostly unique
# tokens (hashes, base64, minified code) can reach below the 1MB body and file limits. The function
# indexes only the leading 100,000 characters of such text, so that the write still succeeds.
SQL = """
-- migration-analyzer: safe reason=updates no rows; UPDATE appears only in the trigger event lists (BEFORE INSERT OR UPDATE OF ...)
CREATE OR REPLACE FUNCTION llm_skill_search_vector(source text) RETURNS tsvector
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
BEGIN
    RETURN to_tsvector('english'::regconfig, source);
EXCEPTION WHEN program_limit_exceeded THEN
    RETURN to_tsvector('english'::regconfig, left(source, 100000));
END
$$;

CREATE OR REPLACE FUNCTION llm_skill_set_search_vector() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_vector := llm_skill_search_vector(NEW.body);
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION llm_skill_file_set_search_vector() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_vector := llm_skill_search_vector(NEW.content);
    RETURN NEW;
END
$$;

ALTER TABLE llm_analytics_llmskill ADD COLUMN IF NOT EXISTS search_vector tsvector;
ALTER TABLE llm_analytics_llmskillfile ADD COLUMN IF NOT EXISTS search_vector tsvector;

DROP TRIGGER IF EXISTS llm_skill_search_vector ON llm_analytics_llmskill;
CREATE TRIGGER llm_skill_search_vector
    BEFORE INSERT OR UPDATE OF body ON llm_analytics_llmskill
    FOR EACH ROW EXECUTE FUNCTION llm_skill_set_search_vector();

DROP TRIGGER IF EXISTS llm_skill_file_search_vector ON llm_analytics_llmskillfile;
CREATE TRIGGER llm_skill_file_search_vector
    BEFORE INSERT OR UPDATE OF content ON llm_analytics_llmskillfile
    FOR EACH ROW EXECUTE FUNCTION llm_skill_file_set_search_vector();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS llm_skill_search_vector ON llm_analytics_llmskill;
DROP TRIGGER IF EXISTS llm_skill_file_search_vector ON llm_analytics_llmskillfile;
ALTER TABLE llm_analytics_llmskill DROP COLUMN IF EXISTS search_vector;
ALTER TABLE llm_analytics_llmskillfile DROP COLUMN IF EXISTS search_vector;
DROP FUNCTION IF EXISTS llm_skill_set_search_vector();
DROP FUNCTION IF EXISTS llm_skill_file_set_search_vector();
DROP FUNCTION IF EXISTS llm_skill_search_vector(text);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("skills", "0010_communityskill_kind_communityskill_scout_config"),
    ]

    operations = [
        migrations.RunSQL(sql=SQL, reverse_sql=REVERSE_SQL),
    ]
