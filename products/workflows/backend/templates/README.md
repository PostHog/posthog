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
   - Create a new file in this directory with the naming pattern: `<template_name>.template.py`
   - Use lowercase and underscores for the filename (e.g., `welcome_email_sequence.template.py`)

3. **Add the template code**:

   ```python
   template = {
       'data': r"""
   {
     "id": "your-template-id",
     "name": "Your Template Name",
     "description": "Template description",
     "scope": "global",
     ...
   }
   """
   }
   ```

   Simply paste the JSON you copied from the "See JSON" modal directly into the `data` field as a multi-line string using triple quotes (`"""`)

4. **Register the template in `__init__.py`**:
   - Open `__init__.py` in this directory
   - Add an import for your new template file (remove the `.template.py` extension):

     ```python
     from . import (
         announce_a_new_feature,
         onboarding_started_but_not_completed,
         trial_started_upgrade_nudge,
         welcome_email_sequence,
         your_new_template,  # Add this line
     )
     ```

   - Add your template module to the `TEMPLATE_MODULES` list:

     ```python
     TEMPLATE_MODULES = [
         announce_a_new_feature,
         onboarding_started_but_not_completed,
         trial_started_upgrade_nudge,
         welcome_email_sequence,
         your_new_template,  # Add this line
     ]
     ```

## Editing an Existing Template

You can export the current version from the UI, make changes, and paste the updated JSON back into the file.

## Template Loading and Validation

Templates are:

- **Loaded on startup**: All templates are loaded & cached when the application starts
- **Validated automatically**: Each template is validated to ensure correctness
- **Invalid templates are skipped**: If a template fails validation, it will be logged but won't prevent other templates from loading

## Important Notes

- **Keep IDs stable**: Once a template is deployed, don't change its ID
- **Test thoroughly**: Always test templates before committing
- **Watch for secrets**: Make sure the template doesn't contain any secret keys or other data we want to keep private
- **r-strings**: Note that data must be an r-string (r"""), otherwise parsing the json will fail
- **Import registration required**: New templates must be imported in `__init__.py` to be loaded
