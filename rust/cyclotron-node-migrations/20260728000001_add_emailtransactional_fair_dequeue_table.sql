-- Fair dequeue for the emailtransactional queue.
--
-- Same per-team monotonic counter pattern as cyclotron_email_team_seq, but a
-- separate table: the counter encodes each team's lifetime send position, so
-- sharing the email table would make a team with a large marketing history
-- permanently sort behind every other tenant in the transactional queue —
-- exactly the teams the dedicated queue is meant to protect.
CREATE TABLE IF NOT EXISTS cyclotron_emailtransactional_team_seq (
    team_id INT PRIMARY KEY,
    counter BIGINT NOT NULL
);
