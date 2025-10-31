# PostHog Tasks

Tasks are units of work for an agent to perform, much like tasks you'd get in an issue tracker. Tasks can automatically checkout a repository in a sandbox environment, generate code changes and create pull requests.

## How Tasks Work

### Core Components

**Task**: A unit of work with a title, description, and repository configuration. Each task moves through stages in a workflow and can trigger automated actions.

**Workflow**: A sequence of stages that a task progresses through (e.g., Plan → Code → Review → Complete). Each team has a default workflow, and tasks automatically use it unless specified otherwise. You probably just want to use the default workflow.

**Stages**: Individual steps within a workflow. Stages can have agents attached that automatically perform work when a task enters that stage.

**Temporal Integration**: Tasks use Temporal workflows for asynchronous processing. When you create and run a task, it triggers a background workflow that executes the task in a sandbox environment using our coding agent, which [you can find here](http://github.com/posthog/agent).

### Feature Flag

Tasks require the `tasks` feature flag to be enabled for the user's organization, and is currently in alpha testing and should not be released to customers yet.

## Creating and Running Tasks

### How can I create a task?

To run a task directly, you can run the `Task.create_and_run` method and specify a repository for the task.

```python
task = Task.create_and_run(
    team=team,
    title="Add dark mode to settings page",
    description="Implement dark mode toggle and theme switching",
    origin_product="error_tracking",
    user_id=user.id,
    repository="posthog/posthog",  # Format: "organization/repository"
)
```

It's that easy. This will add the task to a temporal queue, and kick off a workflow that will handle creating a sandbox environment, executing a coding agent for the task, and submitting a PR at the end of it.

## Parameters

### Required Parameters

- **`team`** (`Team`): The team this task belongs to
- **`title`** (`str`): Short, descriptive title for the task
- **`description`** (`str`): Detailed description of what needs to be done
- **`origin_product`** (`str`): The product this task originated from.
- **`user_id`** (`int`): ID of the user creating the task (this is required to validate the feature flag, and also to create a personal api key for interacting with PostHog).
- **`repository`** (`str`): Repository to work with in format `"org/repo"` (e.g., `"posthog/posthog-js"`). The task will be scoped to this repository, and the PR at the end of it will be to the main branch of this repo.

## What Happens When You Create and Run

1. **Task Creation**: A task record is created in the database
2. **Auto-Configuration**:
   - Automatically finds and attaches the team's GitHub integration (if available)
   - Auto-assigns the team's default workflow
   - Places task in the first stage of the workflow
   - Generates a unique task number and slug (e.g., `POS-123`)
3. **Validation**: Checks that a workflow is configured for the team
4. **Workflow Trigger**: Starts a Temporal workflow in the background that:
   - Validates the `tasks` feature flag for the user's organization
   - Executes any automated agents configured for the task's stage
   - Can create GitHub branches, generate code, and create PRs depending on what agents are available in the workflow

## Best Practices

### Use Descriptive Titles and Descriptions

```python
# Good
task = Task.create_and_run(
    team=team,
    title="Fix race condition in event ingestion pipeline",
    description="""
    When processing high-volume events, we're seeing duplicate entries
    in the events table. This appears to be caused by concurrent writes
    not properly checking for existing records.

    Expected behavior: No duplicate events
    Current behavior: ~2% duplication rate under high load
    """,
    origin_product="error_tracking",
    user_id=user.id,
)

# Bad
task = Task.create_and_run(
    team=team,
    title="Fix bug",
    description="Something is broken",
    origin_product="user_created",
    user_id=user.id,
)
```

### Error Handling

The method raises exceptions that you should handle:

```python
try:
    task = Task.create_and_run(
        team=team,
        title="Implement new feature",
        description="Add support for custom domains",
        origin_product="user_created",
        user_id=user.id,
        repository="invalid-format",  # Missing "/"
    )
except ValueError as e:
    # Handle validation errors (invalid repository format, no workflow configured, etc.)
    logger.error(f"Failed to create task: {e}")
except User.DoesNotExist:
    # Handle invalid user_id
    logger.error(f"User {user_id} does not exist")
```

## Examples

### Error Tracking Integration

```python
def create_task_from_error(error_group, team, user_id):
    task = Task.create_and_run(
        team=team,
        title=f"Fix: {error_group.title}",
        description=f"""
        Error: {error_group.message}
        Occurrences: {error_group.count}
        First seen: {error_group.first_seen}
        Last seen: {error_group.last_seen}

        Stack trace:
        {error_group.stack_trace}
        """,
        origin_product="error_tracking",
        user_id=user_id,
        repository="posthog/posthog",
    )
    return task
```

### Support Queue Integration

```python
def create_task_from_support_ticket(ticket, team, user_id):
    repository = extract_repository_from_ticket(ticket)

    task = Task.create_and_run(
        team=team,
        title=f"Support: {ticket.subject}",
        description=f"""
        Ticket: {ticket.number}
        Customer: {ticket.customer_name}
        Priority: {ticket.priority}

        {ticket.description}
        """,
        origin_product="support_queue",
        user_id=user_id,
        repository=repository,
    )
    return task
```
