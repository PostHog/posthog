import json
from sys import argv

from .posthog_csv import PosthogCSV

if __name__ == "__main__":
    path = argv[1]
    with open('scripts/csv_parser/templates/google_analytics.json') as file:
        settings = json.load(file)
    posthog_csv = PosthogCSV(path, settings)

    posthog_csv.preview()

    # if input("Send to posthog (Y/N):") == 'Y':
    posthog_csv.send()