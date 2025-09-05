use common_database::{PostgresReader, PostgresWriter};

/// Routes database queries to the appropriate pool based on the table being queried.
///
/// When persons tables are in a separate database, this router ensures queries
/// go to the correct database:
/// - Persons tables (posthog_persondistinctid, posthog_person, posthog_featureflaghashkeyoverride, etc.)
///   go to the persons database
/// - Non-persons tables (posthog_featureflag, posthog_team, posthog_grouptypemapping, etc.)
///   go to the main database
#[derive(Clone)]
pub struct PostgresRouter {
    pub persons_reader: PostgresReader,
    pub persons_writer: PostgresWriter,
    pub non_persons_reader: PostgresReader,
    pub non_persons_writer: PostgresWriter,
}

impl PostgresRouter {
    pub fn new(
        persons_reader: PostgresReader,
        persons_writer: PostgresWriter,
        non_persons_reader: PostgresReader,
        non_persons_writer: PostgresWriter,
    ) -> Self {
        Self {
            persons_reader,
            persons_writer,
            non_persons_reader,
            non_persons_writer,
        }
    }

    pub fn get_persons_reader(&self) -> &PostgresReader {
        &self.persons_reader
    }

    pub fn get_persons_writer(&self) -> &PostgresWriter {
        &self.persons_writer
    }

    pub fn get_non_persons_reader(&self) -> &PostgresReader {
        &self.non_persons_reader
    }

    pub fn get_non_persons_writer(&self) -> &PostgresWriter {
        &self.non_persons_writer
    }
}
