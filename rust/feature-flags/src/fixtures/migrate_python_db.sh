#!/bin/bash

# Set the project directory
# TODO: Handle for CI and local
PROJECT_DIR="/Users/neilkakkar/Project/posthog"

# Navigate to the project directory
cd "$PROJECT_DIR"

# Activate the virtual environment
source env/bin/activate

# Set the DEBUG environment variable
export DEBUG=1

# Set DATABASE_URL environment variable
export DATABASE_URL="postgres://posthog:posthog@localhost:5432/test_posthog_rs"


# Run the Django migration command
python manage.py migrate

# Deactivate the virtual environment
deactivate