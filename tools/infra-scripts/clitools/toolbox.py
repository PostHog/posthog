#!/usr/bin/env python3
"""
Toolbox command for connecting to PostHog toolbox pods in a Kubernetes environment.
"""

import os
import sys
import argparse
from datetime import datetime, timedelta

# Add the current directory to the path to allow importing from the toolbox package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import functions from the modular package
from toolbox.kubernetes import select_context
from toolbox.pod import claim_pod, connect_to_pod, delete_pod, get_toolbox_pod
from toolbox.user import get_current_user


def main():
    """Main entry point for the toolbox command."""
    try:
        # If we're in a flox environment, exit
        if "FLOX_ENV" in os.environ:
            print("⚠️ Please exit the flox environment by typing `exit` before connecting to a toolbox.")  # noqa: T201
            sys.exit(0)

        # Set up argument parser
        parser = argparse.ArgumentParser(
            description="Connect to a toolbox pod and manage pod claims. This script will automatically connect you to your latest claimed pod.",
            epilog="Example: toolbox.py --claim-duration 24  # Claims a pod for 24 hours",
        )
        parser.add_argument(
            "--claim-duration",
            type=float,
            default=12,
            help="Duration in hours to claim the pod for (default: 12). The pod will be automatically terminated after this duration.",
        )
        parser.add_argument(
            "--update-claim",
            action="store_true",
            help="Update the termination time of your existing claimed pod instead of claiming a new one.",
        )
        args = parser.parse_args()

        print("🛠️  Connecting to toolbox pod...")  # noqa: T201

        # Let user select kubernetes context
        selected_context = select_context()
        print(f"🔄 Using kubernetes context: {selected_context}")  # noqa: T201

        # Get current user labels
        user_labels = get_current_user()
        print(f"👤 Current user labels: {user_labels}")  # noqa: T201

        # Get available pod
        pod_name, is_already_claimed = get_toolbox_pod(user_labels["toolbox-claimed"], check_claimed=True)
        print(f"🎯 Found pod: {pod_name}")  # noqa: T201

        # Calculate duration
        future_time = datetime.now() + timedelta(hours=args.claim_duration)
        timestamp = int(future_time.timestamp())
        human_readable = future_time.strftime("%Y-%m-%d %H:%M:%S")

        # Claim or update pod
        if not is_already_claimed or args.update_claim:
            print(f"⏰ {'Updating' if is_already_claimed else 'Setting'} pod termination time to: {human_readable}")  # noqa: T201
            claim_pod(pod_name, user_labels, timestamp)
            print(f"✅ Successfully {'updated' if is_already_claimed else 'claimed'} pod: {pod_name}")  # noqa: T201
        else:
            print("✅ Connecting to your existing pod (use --update-claim to extend the duration)")  # noqa: T201

        try:
            connect_to_pod(pod_name)
        finally:
            delete_pod(pod_name)
    except KeyboardInterrupt:
        print("\n👋 Goodbye! \n \n Did something not work as expected? Ask in #team-infrastructure")  # noqa: T201
        sys.exit(0)


if __name__ == "__main__":
    main()
