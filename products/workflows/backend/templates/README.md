# Workflow Templates

This directory contains global workflow templates that are stored in code and version controlled.

## Creating a New Template

1. **Export the template JSON** from the UI:
   - Create or edit a workflow in the PostHog UI
   - Click "Save as template" from the workflow menu
   - Select "Official (visible to everyone)" as the scope
   - Click "See JSON" to open the JSON modal
   - Copy the JSON using the copy button

2. **Create a new template file**:
   - Create a new JSON file in this directory with the naming pattern: `<template_name>_template.json`
   - Use lowercase and underscores for the filename (e.g., `welcome_email_sequence_template.json`)

3. **Add the template JSON**:
   - Paste the JSON you copied from the "See JSON" modal directly into the file
   - Ensure the JSON is valid and properly formatted
   - The file should contain a single JSON object with the template data

4. **Register the template in `__init__.py`**:
   - Open `__init__.py` in this directory
   - Add your template filename to the `TEMPLATE_FILES` list:

     ```python
     TEMPLATE_FILES = [
         "announce_a_new_feature_template.json",
         "onboarding_started_but_not_completed_template.json",
         "trial_started_upgrade_nudge_template.json",
         "welcome_email_sequence_template.json",
         "your_new_template.json",  # Add this line
     ]
     ```

## Editing an Existing Template

You can export the current version from the UI, make changes, and paste the updated JSON back into the file. The JSON file format makes it easy to edit templates directly.

## Template Loading and Validation

Templates are:

- **Loaded on startup**: All templates are loaded & cached when the application starts
- **Validated automatically**: Each template is validated to ensure correctness
- **Invalid templates are skipped**: If a template fails validation, it will be logged but won't prevent other templates from loading

## Important Notes

- **Keep IDs stable**: Once a template is deployed, don't change its ID
- **Test thoroughly**: Always test templates before committing
- **Watch for secrets**: Make sure the template doesn't contain any secret keys or other data we want to keep private
- **Valid JSON required**: The JSON file must be valid JSON - use a JSON linter/formatter if needed
- **File registration required**: New templates must be added to `TEMPLATE_FILES` in `__init__.py` to be loaded
