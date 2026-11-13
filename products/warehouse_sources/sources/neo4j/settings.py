API_VERSION = "v2"
PAGE_SIZE = 1_000
MAX_ROWS_PER_SYNC = 1_000_000
REQUEST_TIMEOUT = (10, 120)

NON_RETRYABLE_ERRORS = {
    "401 Client Error": "Neo4j authentication failed. Check your database username and password.",
    "403 Client Error": "Neo4j denied access. Ask your database administrator for read access.",
    "404 Client Error": "Neo4j Query API was not found. Check the host, database, and Query API configuration.",
    "Neo.ClientError.Security.Unauthorized": "Neo4j authentication failed. Check your database username and password.",
    "Neo.ClientError.Security.CredentialsExpired": "Your Neo4j password has expired. Change it before you connect.",
    "Neo.ClientError.Security.Forbidden": "Neo4j denied access. Ask your database administrator for read access.",
    "Neo.ClientError.Security.TokenExpired": "Your Neo4j credentials have expired. Update the connection credentials.",
    "Neo.ClientError.Database.DatabaseNotFound": "Neo4j could not find the database. Check the database name.",
    "Neo.ClientError.": "Neo4j rejected the query. Check the database permissions and Query API configuration.",
    "Neo4j sync row limit exceeded": "This Neo4j table exceeds the import limit of 1,000,000 rows. Select a smaller label or relationship type.",
    "Neo4j property conflicts": "A Neo4j property uses a reserved column name. Rename the property before importing this table.",
    "Invalid Neo4j host": "Enter a public HTTPS host without a path, query, or embedded credentials.",
    "Invalid Neo4j database": "Enter a valid Neo4j database name.",
    "Invalid Neo4j table": "Select a discovered Neo4j node label or relationship type.",
    "Neo4j redirects are not allowed": "Enter the final HTTPS address of your Neo4j server.",
}
