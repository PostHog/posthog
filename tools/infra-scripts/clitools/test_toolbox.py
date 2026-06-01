#!/usr/bin/env python3

import os
import json
import time
import signal
import subprocess
import importlib.util

import unittest
from unittest.mock import MagicMock, patch

from toolbox.kubernetes import (
    get_available_contexts,
    get_current_context,
    kubectl_cmd,
    select_context,
    switch_context,
    validate_context,
)
from toolbox.pod import ClaimRaceError, claim_pod, delete_pod, get_toolbox_pod
from toolbox.user import get_current_user, parse_arn, sanitize_label

# Load toolbox.py (the script with main() and POOLS) by file path, since the
# `toolbox` package shadows it in normal import resolution.
_TOOLBOX_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolbox.py")
_spec = importlib.util.spec_from_file_location("_toolbox_script", _TOOLBOX_SCRIPT_PATH)
toolbox_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(toolbox_script)


class TestToolbox(unittest.TestCase):
    def test_kubectl_cmd_without_context(self):
        """kubectl_cmd with context=None returns the same shape as a bare kubectl call."""
        self.assertEqual(kubectl_cmd("get", "pods"), ["kubectl", "get", "pods"])

    def test_kubectl_cmd_with_context(self):
        """kubectl_cmd injects --context= so we can scope to a cluster without mutating kubeconfig."""
        self.assertEqual(
            kubectl_cmd("get", "pods", context="posthog-dev"),
            ["kubectl", "--context=posthog-dev", "get", "pods"],
        )

    def test_kubectl_cmd_empty_context_is_treated_as_unset(self):
        """An empty string for context means 'no override', matching get_current_context() returning ''."""
        self.assertEqual(kubectl_cmd("get", "pods", context=""), ["kubectl", "get", "pods"])

    def test_sanitize_label(self):
        """Test label sanitization function."""
        # Test basic email sanitization
        self.assertEqual(sanitize_label("user@example.com"), "user_at_example.com")

        # Test with special characters
        self.assertEqual(sanitize_label("user.name@example.com"), "user.name_at_example.com")

        # Test with underscores
        self.assertEqual(sanitize_label("user_name@example.com"), "user_name_at_example.com")

        # Test with leading/trailing underscores
        self.assertEqual(sanitize_label("_user@example.com_"), "user_at_example.com")

    def test_sanitize_label_truncation(self):
        long_arn = (
            "arn:aws:sts::169684386827:assumed-role/custom-role-name/" + "averyveryveryveryverylongemail@posthog.com"
        )
        sanitized = sanitize_label(long_arn)
        self.assertTrue(sanitized.startswith("arn_aws_sts__169684386827_assu"))
        self.assertIn("longemail_at_posthog.com", sanitized)
        self.assertLessEqual(len(sanitized), 63)

    def test_parse_arn_valid(self):
        """Test parsing valid AWS STS ARN."""
        arn = "arn:aws:sts::169684386827:assumed-role/AWSReservedSSO_developers_0847e649a00cc5e7/michael.k@posthog.com"
        expected = {"toolbox-claimed": "michael.k_at_posthog.com", "role-name": "developers", "assumed-role": "true"}
        self.assertEqual(parse_arn(arn, claimed_label_key="toolbox-claimed"), expected)

    def test_parse_arn_different_role(self):
        """Test parsing ARN with different role."""
        arn = "arn:aws:sts::169684386827:assumed-role/AWSReservedSSO_admins_0847e649a00cc5e7/michael.k@posthog.com"
        expected = {"toolbox-claimed": "michael.k_at_posthog.com", "role-name": "admins", "assumed-role": "true"}
        self.assertEqual(parse_arn(arn, claimed_label_key="toolbox-claimed"), expected)

    def test_parse_arn_unexpected_format(self):
        """Test parsing ARN with unexpected role format."""
        arn = "arn:aws:sts::169684386827:assumed-role/custom-role-name/michael.k@posthog.com"
        expected = {"toolbox-claimed": "arn_aws_sts__169684386827_assum_e-name_michael.k_at_posthog.com"}
        self.assertEqual(parse_arn(arn, claimed_label_key="toolbox-claimed"), expected)

    def test_parse_arn_jumphost_label_key(self):
        """Pool-specific claimed_label_key reaches every return path of parse_arn."""
        arn = "arn:aws:sts::169684386827:assumed-role/AWSReservedSSO_developers_0847e649a00cc5e7/michael.k@posthog.com"
        expected = {
            "flags-jumphost-claimed": "michael.k_at_posthog.com",
            "role-name": "developers",
            "assumed-role": "true",
        }
        self.assertEqual(parse_arn(arn, claimed_label_key="flags-jumphost-claimed"), expected)

    @patch("subprocess.run")
    def test_get_current_user(self, mock_run):
        """Test getting current user from kubectl auth."""
        # Mock kubectl auth whoami response
        mock_response = MagicMock()
        mock_response.stdout = json.dumps(
            {
                "status": {
                    "userInfo": {
                        "username": "sso-developers",
                        "extra": {
                            "arn": [
                                "arn:aws:sts::169684386827:assumed-role/AWSReservedSSO_developers_0847e649a00cc5e7/michael.k@posthog.com"
                            ],
                            "sessionName": ["michael.k@posthog.com"],
                        },
                    }
                }
            }
        )
        mock_run.return_value = mock_response

        user_labels = get_current_user(claimed_label_key="toolbox-claimed")
        expected = {"toolbox-claimed": "michael.k_at_posthog.com", "role-name": "developers", "assumed-role": "true"}
        self.assertEqual(user_labels, expected)
        mock_run.assert_called_once_with(
            ["kubectl", "auth", "whoami", "-o", "json"], capture_output=True, text=True, check=True
        )

    @patch("subprocess.run")
    def test_get_current_user_with_context(self, mock_run):
        """get_current_user with context= scopes the whoami call to that context."""
        mock_response = MagicMock()
        mock_response.stdout = json.dumps(
            {
                "status": {
                    "userInfo": {
                        "username": "sso-developers",
                        "extra": {
                            "arn": [
                                "arn:aws:sts::169684386827:assumed-role/AWSReservedSSO_developers_0847e649a00cc5e7/michael.k@posthog.com"
                            ],
                        },
                    }
                }
            }
        )
        mock_run.return_value = mock_response

        get_current_user(claimed_label_key="toolbox-claimed", context="posthog-dev")
        mock_run.assert_called_once_with(
            ["kubectl", "--context=posthog-dev", "auth", "whoami", "-o", "json"],
            capture_output=True,
            text=True,
            check=True,
        )

    @patch("sys.exit")
    @patch("builtins.print")
    @patch("subprocess.run")
    def test_get_current_user_token_expired(self, mock_run, mock_print, mock_exit):
        """Test getting current user when token has expired and refresh failed."""
        # Mock kubectl auth whoami to raise error with token expiration message
        error = subprocess.CalledProcessError(
            returncode=1,
            cmd=["kubectl", "auth", "whoami", "-o", "json"],
            stderr="Token has expired and refresh failed",
        )
        mock_run.side_effect = error

        get_current_user(claimed_label_key="toolbox-claimed")

        mock_run.assert_called_once_with(
            ["kubectl", "auth", "whoami", "-o", "json"], capture_output=True, text=True, check=True
        )
        mock_print.assert_any_call(
            "Token has expired and refresh failed, please reauthenticate with `aws sso login --profile=<your-profile>`"
        )
        mock_exit.assert_called_once_with(1)

    @patch("subprocess.run")
    def test_get_toolbox_pod(self, mock_run):
        """get_toolbox_pod returns (name, claimed, resource_version) for a fresh unclaimed pod."""
        mock_response = MagicMock()
        mock_response.stdout = json.dumps(
            {
                "items": [
                    {
                        "metadata": {
                            "name": "toolbox-pod-1",
                            "resourceVersion": "12345",
                            "labels": {
                                "app.kubernetes.io/name": "posthog-toolbox-django",
                                "pod-template-hash": "749c5d8db",
                                "posthog.com/image": "posthog",
                                "posthog.com/team": "infra",
                                "role": "toolbox",
                            },
                            "deletionTimestamp": None,
                        },
                        "status": {"phase": "Running"},
                    }
                ]
            }
        )
        mock_run.return_value = mock_response

        pod_name, is_claimed, resource_version = get_toolbox_pod(
            "michael.k_at_posthog.com",
            app_label="posthog-toolbox-django",
            claimed_label_key="toolbox-claimed",
            namespace="posthog",
        )
        self.assertEqual(pod_name, "toolbox-pod-1")
        self.assertFalse(is_claimed)
        self.assertEqual(resource_version, "12345")
        mock_run.assert_called_once_with(
            [
                "kubectl",
                "get",
                "pods",
                "-n",
                "posthog",
                "-l",
                "app.kubernetes.io/name=posthog-toolbox-django",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

    @patch("subprocess.run")
    def test_get_toolbox_pod_with_context(self, mock_run):
        """get_toolbox_pod with context= passes --context to kubectl get pods."""
        mock_response = MagicMock()
        mock_response.stdout = json.dumps(
            {
                "items": [
                    {
                        "metadata": {
                            "name": "toolbox-pod-1",
                            "resourceVersion": "12345",
                            "labels": {"app.kubernetes.io/name": "posthog-toolbox-django"},
                            "deletionTimestamp": None,
                        },
                        "status": {"phase": "Running"},
                    }
                ]
            }
        )
        mock_run.return_value = mock_response

        get_toolbox_pod(
            "michael.k_at_posthog.com",
            app_label="posthog-toolbox-django",
            claimed_label_key="toolbox-claimed",
            namespace="posthog",
            context="posthog-dev",
        )
        mock_run.assert_called_once_with(
            [
                "kubectl",
                "--context=posthog-dev",
                "get",
                "pods",
                "-n",
                "posthog",
                "-l",
                "app.kubernetes.io/name=posthog-toolbox-django",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

    @patch("subprocess.run")
    def test_get_toolbox_pod_returns_existing_claim_with_rv(self, mock_run):
        """An already-claimed pod returns is_claimed=True and the observed resourceVersion."""
        mock_response = MagicMock()
        mock_response.stdout = json.dumps(
            {
                "items": [
                    {
                        "metadata": {
                            "name": "toolbox-pod-1",
                            "resourceVersion": "55555",
                            "labels": {
                                "app.kubernetes.io/name": "posthog-toolbox-django",
                                "toolbox-claimed": "michael.k_at_posthog.com",
                            },
                            "deletionTimestamp": None,
                        },
                        "status": {"phase": "Running"},
                    }
                ]
            }
        )
        mock_run.return_value = mock_response

        pod_name, is_claimed, rv = get_toolbox_pod(
            "michael.k_at_posthog.com",
            app_label="posthog-toolbox-django",
            claimed_label_key="toolbox-claimed",
            namespace="posthog",
        )
        self.assertEqual(pod_name, "toolbox-pod-1")
        self.assertTrue(is_claimed)
        self.assertEqual(rv, "55555")

    @patch("subprocess.run")
    def test_claim_pod(self, mock_run):
        """Test claiming a pod."""
        # Mock kubectl get pod response
        mock_get_response = MagicMock()
        mock_get_response.stdout = json.dumps({"app.kubernetes.io/name": "posthog-toolbox-django"})

        # Mock kubectl label and annotate responses
        mock_label_response = MagicMock()
        mock_annotate_response = MagicMock()

        # Set up the side effect to handle all kubectl calls
        mock_run.side_effect = [
            mock_get_response,  # get pod labels
            mock_annotate_response,  # add annotation
            mock_label_response,  # add new labels
            mock_label_response,  # wait for pod
        ]

        user_labels = {"toolbox-claimed": "michael.k_at_posthog.com", "role-name": "developers", "assumed-role": "true"}
        claim_pod("toolbox-pod-1", user_labels, 1234567890, namespace="posthog")

        # Verify kubectl commands were called correctly
        self.assertEqual(mock_run.call_count, 4)

        # Get all calls made to kubectl
        calls = mock_run.call_args_list

        # Verify the first call to get pod labels
        self.assertEqual(
            calls[0][0][0],
            ["kubectl", "get", "pod", "-n", "posthog", "toolbox-pod-1", "-o", "jsonpath={.metadata.labels}"],
        )

        # Verify the annotation call
        self.assertEqual(
            calls[1][0][0],
            [
                "kubectl",
                "annotate",
                "pod",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "karpenter.sh/do-not-disrupt=true",
                "--overwrite=true",
            ],
        )

        # Verify the label call
        self.assertEqual(
            calls[2][0][0],
            [
                "kubectl",
                "label",
                "pod",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "toolbox-claimed=michael.k_at_posthog.com",
                "role-name=developers",
                "assumed-role=true",
                "terminate-after=1234567890",
            ],
        )

        # Verify the wait call
        self.assertEqual(
            calls[3][0][0],
            ["kubectl", "wait", "--for=condition=Ready", "--timeout=5m", "-n", "posthog", "pod", "toolbox-pod-1"],
        )

    @patch("subprocess.run")
    def test_claim_pod_custom_duration(self, mock_run):
        """Test claiming a pod with custom duration."""
        # Mock kubectl get pod response
        mock_get_response = MagicMock()
        mock_get_response.stdout = json.dumps({"app.kubernetes.io/name": "posthog-toolbox-django"})

        # Mock kubectl label and annotate responses
        mock_label_response = MagicMock()
        mock_annotate_response = MagicMock()

        # Set up the side effect to handle all kubectl calls
        mock_run.side_effect = [
            mock_get_response,  # get pod labels
            mock_annotate_response,  # add annotation
            mock_label_response,  # add new labels
            mock_label_response,  # wait for pod
        ]

        # Calculate timestamp 4 hours from now
        future_timestamp = int(time.time()) + (4 * 60 * 60)

        user_labels = {"toolbox-claimed": "michael.k_at_posthog.com", "role-name": "developers", "assumed-role": "true"}
        claim_pod("toolbox-pod-1", user_labels, future_timestamp, namespace="posthog")

        # Verify kubectl commands were called correctly
        self.assertEqual(mock_run.call_count, 4)

        # Get all calls made to kubectl
        calls = mock_run.call_args_list

        # Verify the label call includes the future timestamp
        self.assertEqual(
            calls[2][0][0],
            [
                "kubectl",
                "label",
                "pod",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "toolbox-claimed=michael.k_at_posthog.com",
                "role-name=developers",
                "assumed-role=true",
                f"terminate-after={future_timestamp}",
            ],
        )

    @patch("subprocess.run")
    def test_update_claim(self, mock_run):
        """Test updating an existing pod claim."""
        # Mock kubectl get pod response
        mock_get_response = MagicMock()
        mock_get_response.stdout = json.dumps(
            {
                "app.kubernetes.io/name": "posthog-toolbox-django",
                "toolbox-claimed": "michael.k_at_posthog.com",
                "role-name": "developers",
                "assumed-role": "true",
                "terminate-after": "1234567890",
            }
        )

        # Mock kubectl label and annotate responses
        mock_label_response = MagicMock()
        mock_annotate_response = MagicMock()

        # Set up the side effect to handle all kubectl calls
        mock_run.side_effect = [
            mock_get_response,  # get pod labels
            mock_label_response,  # batch-remove existing labels
            mock_annotate_response,  # add annotation
            mock_label_response,  # add new labels
            mock_label_response,  # wait for pod
        ]

        # Calculate new timestamp 24 hours from now
        future_timestamp = int(time.time()) + (24 * 60 * 60)

        user_labels = {"toolbox-claimed": "michael.k_at_posthog.com", "role-name": "developers", "assumed-role": "true"}
        claim_pod("toolbox-pod-1", user_labels, future_timestamp, namespace="posthog")

        # Verify kubectl commands were called correctly
        self.assertEqual(mock_run.call_count, 5)

        # Get all calls made to kubectl
        calls = mock_run.call_args_list

        # Verify the first call to get pod labels
        self.assertEqual(
            calls[0][0][0],
            ["kubectl", "get", "pod", "-n", "posthog", "toolbox-pod-1", "-o", "jsonpath={.metadata.labels}"],
        )

        # Verify the batched label-removal call (single kubectl invocation)
        self.assertEqual(
            calls[1][0][0],
            [
                "kubectl",
                "label",
                "pod",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "toolbox-claimed-",
                "role-name-",
                "assumed-role-",
                "terminate-after-",
            ],
        )

        # Verify the annotation call
        self.assertEqual(
            calls[2][0][0],
            [
                "kubectl",
                "annotate",
                "pod",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "karpenter.sh/do-not-disrupt=true",
                "--overwrite=true",
            ],
        )

        # Verify the label call
        self.assertEqual(
            calls[3][0][0],
            [
                "kubectl",
                "label",
                "pod",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "toolbox-claimed=michael.k_at_posthog.com",
                "role-name=developers",
                "assumed-role=true",
                f"terminate-after={future_timestamp}",
            ],
        )

        # Verify the wait call
        self.assertEqual(
            calls[4][0][0],
            ["kubectl", "wait", "--for=condition=Ready", "--timeout=5m", "-n", "posthog", "pod", "toolbox-pod-1"],
        )

    @patch("subprocess.run")
    def test_claim_pod_with_resource_version_passes_flag_on_first_mutation(self, mock_run):
        """When resource_version is set, the FIRST mutating kubectl call carries --resource-version=<rv>.

        Subsequent calls drop the flag because the resourceVersion advances after every
        successful write; carrying the original rv on later calls would 409 against
        ourselves.
        """
        mock_get_response = MagicMock()
        mock_get_response.stdout = json.dumps({"app.kubernetes.io/name": "posthog-toolbox-django"})
        # No labels_to_remove → annotate is the first mutation, so it carries the rv flag.
        mock_run.side_effect = [
            mock_get_response,  # kubectl get pod labels
            MagicMock(),  # annotate (first mutation, with --resource-version)
            MagicMock(),  # label add (no rv flag)
            MagicMock(),  # wait
        ]

        user_labels = {"toolbox-claimed": "u_at_posthog.com"}
        claim_pod("toolbox-pod-1", user_labels, 1234567890, namespace="posthog", resource_version="42")

        annotate_args = mock_run.call_args_list[1][0][0]
        label_args = mock_run.call_args_list[2][0][0]
        self.assertIn("--resource-version=42", annotate_args)
        self.assertNotIn("--resource-version=42", label_args)

    @patch("subprocess.run")
    def test_claim_pod_with_resource_version_attaches_to_label_strip_when_present(self, mock_run):
        """If existing labels need stripping, the strip step (not annotate) is the first mutation."""
        mock_get_response = MagicMock()
        mock_get_response.stdout = json.dumps(
            {
                "app.kubernetes.io/name": "posthog-toolbox-django",
                "pod-template-hash": "abc123",
            }
        )
        mock_run.side_effect = [
            mock_get_response,  # kubectl get pod labels
            MagicMock(),  # label-strip (first mutation, with rv flag)
            MagicMock(),  # annotate (no rv flag)
            MagicMock(),  # label add (no rv flag)
            MagicMock(),  # wait
        ]

        user_labels = {"toolbox-claimed": "u_at_posthog.com"}
        claim_pod("toolbox-pod-1", user_labels, 1234567890, namespace="posthog", resource_version="42")

        strip_args = mock_run.call_args_list[1][0][0]
        annotate_args = mock_run.call_args_list[2][0][0]
        self.assertIn("--resource-version=42", strip_args)
        self.assertNotIn("--resource-version=42", annotate_args)

    @patch("subprocess.run")
    def test_claim_pod_raises_claim_race_error_on_conflict(self, mock_run):
        """A 409 Conflict on the first mutation surfaces as ClaimRaceError so the caller can retry."""
        mock_get_response = MagicMock()
        mock_get_response.stdout = json.dumps({"app.kubernetes.io/name": "posthog-toolbox-django"})
        conflict = subprocess.CalledProcessError(
            returncode=1,
            cmd=["kubectl", "annotate", "pod"],
            stderr="Error from server (Conflict): the object has been modified",
        )
        mock_run.side_effect = [
            mock_get_response,  # kubectl get pod labels
            conflict,  # annotate (first mutation) loses the race
        ]

        user_labels = {"toolbox-claimed": "u_at_posthog.com"}
        with self.assertRaises(ClaimRaceError):
            claim_pod("toolbox-pod-1", user_labels, 1234567890, namespace="posthog", resource_version="42")

    @patch("subprocess.run")
    def test_claim_pod_non_conflict_error_does_not_raise_race(self, mock_run):
        """A non-409 kubectl failure on the first mutation is not a race; the original error path applies."""
        mock_get_response = MagicMock()
        mock_get_response.stdout = json.dumps({"app.kubernetes.io/name": "posthog-toolbox-django"})
        non_conflict = subprocess.CalledProcessError(
            returncode=1,
            cmd=["kubectl", "annotate", "pod"],
            stderr="Error from server (Forbidden): user cannot annotate pods",
        )
        mock_run.side_effect = [
            mock_get_response,  # kubectl get pod labels
            non_conflict,  # annotate fails with a non-409 error
        ]

        user_labels = {"toolbox-claimed": "u_at_posthog.com"}
        with self.assertRaises(SystemExit):
            claim_pod("toolbox-pod-1", user_labels, 1234567890, namespace="posthog", resource_version="42")

    @patch("subprocess.run")
    def test_claim_pod_with_context(self, mock_run):
        """claim_pod with context= passes --context to every kubectl invocation."""
        mock_get_response = MagicMock()
        mock_get_response.stdout = json.dumps({"app.kubernetes.io/name": "posthog-toolbox-django"})
        mock_run.side_effect = [
            mock_get_response,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        ]

        user_labels = {"toolbox-claimed": "u_at_posthog.com"}
        claim_pod("toolbox-pod-1", user_labels, 1234567890, namespace="posthog", context="posthog-dev")

        for call in mock_run.call_args_list:
            cmd = call[0][0]
            self.assertEqual(cmd[0], "kubectl")
            self.assertEqual(cmd[1], "--context=posthog-dev")

    # New tests for Kubernetes context functions
    @patch("subprocess.run")
    def test_get_available_contexts(self, mock_run):
        """Test getting available kubernetes contexts."""
        mock_response = MagicMock()
        mock_response.stdout = "context1\ncontext2\ncontext3"
        mock_run.return_value = mock_response

        contexts = get_available_contexts()

        self.assertEqual(contexts, ["context1", "context2", "context3"])
        mock_run.assert_called_once_with(
            ["kubectl", "config", "get-contexts", "-o", "name"], capture_output=True, text=True, check=True
        )

    @patch("subprocess.run")
    def test_get_available_contexts_empty(self, mock_run):
        """Test getting available kubernetes contexts when none exist."""
        mock_response = MagicMock()
        mock_response.stdout = ""
        mock_run.return_value = mock_response

        contexts = get_available_contexts()

        self.assertEqual(contexts, [])
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_get_available_contexts_error(self, mock_run):
        """Test error handling when getting available contexts fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "kubectl", "error")

        with self.assertRaises(SystemExit):
            get_available_contexts()

        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_get_current_context(self, mock_run):
        """Test getting current kubernetes context."""
        mock_response = MagicMock()
        mock_response.stdout = "current-context"
        mock_run.return_value = mock_response

        context = get_current_context()

        self.assertEqual(context, "current-context")
        mock_run.assert_called_once_with(
            ["kubectl", "config", "current-context"], capture_output=True, text=True, check=True
        )

    @patch("subprocess.run")
    def test_get_current_context_error(self, mock_run):
        """Test error handling when getting current context fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "kubectl", "error")

        context = get_current_context()

        self.assertIsNone(context)
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_switch_context(self, mock_run):
        """Test switching kubernetes context."""
        mock_run.return_value = MagicMock()

        result = switch_context("new-context")

        self.assertTrue(result)
        mock_run.assert_called_once_with(["kubectl", "config", "use-context", "new-context"], check=True)

    @patch("subprocess.run")
    def test_switch_context_error(self, mock_run):
        """Test error handling when switching context fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "kubectl", "error")

        result = switch_context("invalid-context")

        self.assertFalse(result)
        mock_run.assert_called_once()

    @patch("toolbox.kubernetes.get_available_contexts")
    def test_validate_context_known(self, mock_get):
        """validate_context returns True for a context that's in the available list."""
        mock_get.return_value = ["posthog-dev", "posthog-prod"]
        self.assertTrue(validate_context("posthog-dev"))

    @patch("toolbox.kubernetes.get_available_contexts")
    def test_validate_context_unknown(self, mock_get):
        """validate_context returns False for a context that isn't known."""
        mock_get.return_value = ["posthog-dev", "posthog-prod"]
        self.assertFalse(validate_context("posthog-bogus"))

    @patch("toolbox.kubernetes.get_available_contexts")
    @patch("toolbox.kubernetes.get_current_context")
    @patch("builtins.input")
    def test_select_context(self, mock_input, mock_get_current, mock_get_available):
        """Test selecting kubernetes context."""
        # Setup mocks
        mock_get_available.return_value = ["context1", "context2", "context3"]
        mock_get_current.return_value = "context1"
        mock_input.return_value = ""  # User just presses Enter to use current context

        # Call function
        result = select_context()

        # Verify result
        self.assertEqual(result, "context1")
        mock_get_available.assert_called_once()
        mock_get_current.assert_called_once()
        mock_input.assert_called_once()

    @patch("toolbox.kubernetes.get_available_contexts")
    @patch("toolbox.kubernetes.get_current_context")
    @patch("builtins.input")
    def test_select_context_picks_index_without_switching(self, mock_input, mock_get_current, mock_get_available):
        """Picking a context returns the chosen name without calling kubectl config use-context."""
        mock_get_available.return_value = ["context1", "context2", "context3"]
        mock_get_current.return_value = "context1"
        mock_input.return_value = "2"

        with patch("toolbox.kubernetes.switch_context") as mock_switch:
            result = select_context()

        self.assertEqual(result, "context2")
        mock_switch.assert_not_called()

    @patch("toolbox.kubernetes.get_available_contexts")
    @patch("toolbox.kubernetes.get_current_context")
    def test_select_context_current_none(self, mock_get_current, mock_get_available):
        """Test select_context exits if current context is None."""
        mock_get_available.return_value = ["context1", "context2"]
        mock_get_current.return_value = None
        with self.assertRaises(SystemExit):
            select_context()

    @patch("subprocess.run")
    def test_claim_pod_wait_timeout(self, mock_run):
        """Test claim_pod exits if pod does not become ready within 5 minutes."""
        mock_get_response = MagicMock()
        mock_get_response.stdout = json.dumps({"app.kubernetes.io/name": "posthog-toolbox-django"})
        mock_annotate_response = MagicMock()
        mock_label_response = MagicMock()
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return mock_get_response
            elif call_count["n"] == 2:
                return mock_annotate_response
            elif call_count["n"] == 3:
                return mock_label_response
            elif call_count["n"] == 4:
                raise subprocess.CalledProcessError(1, args[0], "Timed out")
            else:
                return mock_label_response

        mock_run.side_effect = side_effect
        user_labels = {"toolbox-claimed": "michael.k_at_posthog.com", "role-name": "developers", "assumed-role": "true"}
        with self.assertRaises(SystemExit):
            claim_pod("toolbox-pod-1", user_labels, 1234567890, namespace="posthog")

    def test_pools_definition(self):
        """POOLS contains both pools with the expected app and claim labels."""
        self.assertEqual(
            toolbox_script.POOLS["toolbox-django"],
            {"app_label": "posthog-toolbox-django", "claimed_label_key": "toolbox-claimed"},
        )
        self.assertEqual(
            toolbox_script.POOLS["flags-cache-jumphost"],
            {"app_label": "flags-cache-jumphost", "claimed_label_key": "flags-jumphost-claimed"},
        )

    def test_exit_for_signal_raises_systemexit_for_sigterm(self):
        """SIGTERM handler routes through sys.exit so atexit-registered cleanup fires."""
        with self.assertRaises(SystemExit) as ctx:
            toolbox_script._exit_for_signal(signal.SIGTERM, None)
        self.assertEqual(ctx.exception.code, 128 + int(signal.SIGTERM))

    def test_exit_for_signal_raises_systemexit_for_sighup(self):
        """SIGHUP handler routes through sys.exit so atexit-registered cleanup fires.

        SIGHUP fires on terminal close (closing iTerm, SSH disconnect, killing a tmux
        pane); without this routing the claimed pod would leak.
        """
        with self.assertRaises(SystemExit) as ctx:
            toolbox_script._exit_for_signal(signal.SIGHUP, None)
        self.assertEqual(ctx.exception.code, 128 + int(signal.SIGHUP))

    @patch("builtins.input")
    @patch("subprocess.run")
    def test_delete_pod_auto_yes_skips_prompt(self, mock_run, mock_input):
        """delete_pod(auto_yes=True) does not call input() and uses --ignore-not-found."""
        delete_pod("toolbox-pod-1", namespace="posthog", auto_yes=True)

        mock_input.assert_not_called()
        mock_run.assert_called_once_with(
            [
                "kubectl",
                "delete",
                "pod",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "--ignore-not-found",
                "--wait=false",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    @patch("builtins.input")
    @patch("subprocess.run")
    def test_delete_pod_with_context_passes_flag(self, mock_run, mock_input):
        """delete_pod with context= scopes the kubectl delete to that context."""
        delete_pod("toolbox-pod-1", namespace="posthog", context="posthog-dev", auto_yes=True)

        mock_input.assert_not_called()
        mock_run.assert_called_once_with(
            [
                "kubectl",
                "--context=posthog-dev",
                "delete",
                "pod",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "--ignore-not-found",
                "--wait=false",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    @patch("builtins.input", return_value="y")
    @patch("subprocess.run")
    def test_delete_pod_prompt_yes_invokes_kubectl(self, mock_run, mock_input):
        """delete_pod(auto_yes=False) with a 'y' response invokes kubectl delete."""
        delete_pod("toolbox-pod-1", namespace="posthog")

        mock_input.assert_called_once()
        mock_run.assert_called_once()

    @patch("builtins.input", return_value="n")
    @patch("subprocess.run")
    def test_delete_pod_prompt_no_skips_kubectl(self, mock_run, mock_input):
        """delete_pod(auto_yes=False) with a non-'y' response does not call kubectl."""
        delete_pod("toolbox-pod-1", namespace="posthog")

        mock_input.assert_called_once()
        mock_run.assert_not_called()

    @patch("builtins.print", side_effect=BrokenPipeError("hung-up PTY"))
    @patch("subprocess.run")
    def test_delete_pod_runs_kubectl_when_stdout_is_broken(self, mock_run, mock_print):
        """delete_pod must still run kubectl delete when stdout is hung up.

        Reproduces the SIGHUP-cleanup leak: when the user closes their terminal
        tab, atexit fires delete_pod *after* the controlling PTY is gone.
        Pre-fix, the very first ``print('🗑️  Deleting pod...')`` raised
        BrokenPipeError before kubectl was reached, leaking a claimed pod.
        """
        delete_pod("toolbox-pod-1", namespace="posthog", auto_yes=True)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "kubectl")
        self.assertIn("delete", cmd)
        self.assertIn("toolbox-pod-1", cmd)

    @patch("builtins.input", side_effect=BrokenPipeError("hung-up PTY"))
    @patch("subprocess.run")
    def test_delete_pod_prompt_path_with_broken_input_skips_delete(self, mock_run, mock_input):
        """When input() can't read (no TTY / hung-up), default to NOT deleting.

        Matches the safety semantics of an explicit user 'n' so we never delete
        a non-auto-delete pod without explicit consent.
        """
        delete_pod("toolbox-pod-1", namespace="posthog", auto_yes=False)

        mock_input.assert_called_once()
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_delete_pod_skips_when_label_does_not_match(self, mock_run):
        """When expected_label_* are passed (atexit path) and the label doesn't match,
        the kubectl delete is skipped to protect against deleting an unclaimed pool pod
        when claim_pod() failed before any label was written.
        """
        # kubectl get returns an empty label value (pod was never claimed).
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        delete_pod(
            "toolbox-pod-1",
            namespace="posthog",
            auto_yes=True,
            expected_label_key="toolbox-claimed",
            expected_label_value="user_at_posthog.com",
        )

        # Exactly one kubectl call: the verification get. No delete was issued.
        self.assertEqual(mock_run.call_count, 1)
        cmd = mock_run.call_args[0][0]
        self.assertIn("get", cmd)
        self.assertNotIn("delete", cmd)

    @patch("subprocess.run")
    def test_delete_pod_proceeds_when_label_matches(self, mock_run):
        """When the label check confirms our claim, delete_pod proceeds with the kubectl delete."""
        # First call (get) returns the matching label value; second call (delete) succeeds.
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="user_at_posthog.com", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]

        delete_pod(
            "toolbox-pod-1",
            namespace="posthog",
            auto_yes=True,
            expected_label_key="toolbox-claimed",
            expected_label_value="user_at_posthog.com",
        )

        self.assertEqual(mock_run.call_count, 2)
        delete_cmd = mock_run.call_args_list[1][0][0]
        self.assertIn("delete", delete_cmd)
        self.assertIn("toolbox-pod-1", delete_cmd)

    @patch("subprocess.run")
    def test_delete_pod_skips_when_label_check_errors(self, mock_run):
        """If the label-verification kubectl get errors out, default to NOT deleting.

        Leaving an orphan to be reaped is preferable to silently shrinking the pool.
        """
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["kubectl", "get"],
            stderr="forbidden",
        )

        delete_pod(
            "toolbox-pod-1",
            namespace="posthog",
            auto_yes=True,
            expected_label_key="toolbox-claimed",
            expected_label_value="user_at_posthog.com",
        )

        # Only the failing get call; no delete attempted.
        self.assertEqual(mock_run.call_count, 1)

    @patch("subprocess.run")
    def test_delete_pod_without_expected_label_skips_verification(self, mock_run):
        """Without expected_label_*, no extra kubectl get is issued (interactive 'y' path)."""
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        delete_pod("toolbox-pod-1", namespace="posthog", auto_yes=True)

        self.assertEqual(mock_run.call_count, 1)
        cmd = mock_run.call_args[0][0]
        self.assertIn("delete", cmd)

    @patch("builtins.print", side_effect=BrokenPipeError("hung-up PTY"))
    @patch("subprocess.run")
    def test_delete_pod_swallows_kubectl_failure_when_stdout_broken(self, mock_run, mock_print):
        """If kubectl delete fails AND stdout is broken, delete_pod must not raise.

        Otherwise a transient kubectl failure during atexit would propagate and
        skip any subsequent atexit handlers.
        """
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["kubectl", "delete"],
            stderr="some error",
        )

        # Should not raise:
        delete_pod("toolbox-pod-1", namespace="posthog", auto_yes=True)

        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_connect_to_pod_returns_zero_on_success(self, mock_run):
        """connect_to_pod returns 0 when kubectl exec exits cleanly."""
        from toolbox.pod import connect_to_pod

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        rc = connect_to_pod("toolbox-pod-1", namespace="posthog")
        self.assertEqual(rc, 0)

    @patch("subprocess.run")
    def test_connect_to_pod_returns_nonzero_on_failure(self, mock_run):
        """connect_to_pod surfaces a non-zero exit code from kubectl exec.

        The original code used subprocess.run without checking returncode, so RBAC
        denials, missing pods, and network failures silently looked successful and
        triggered downstream cleanup of a session that never opened.
        """
        from toolbox.pod import connect_to_pod

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_run.return_value = mock_result

        rc = connect_to_pod("toolbox-pod-1", namespace="posthog")
        self.assertEqual(rc, 1)

    @patch("subprocess.run")
    def test_connect_to_pod_with_context(self, mock_run):
        """connect_to_pod with context= passes --context to kubectl exec."""
        from toolbox.pod import connect_to_pod

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        connect_to_pod("toolbox-pod-1", namespace="posthog", context="posthog-dev")
        mock_run.assert_called_once_with(
            [
                "kubectl",
                "--context=posthog-dev",
                "exec",
                "-it",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "--",
                "bash",
            ]
        )

    def _patch_main_collaborators(self, *, get_pod_returns=("toolbox-pod-1", False, "12345")):
        """Common patch stack for main() integration tests.

        Patches everything main() depends on so the test exercises only the dispatch
        wiring (POOLS lookup, KUBE_CONTEXT branch, kwargs threading, race-retry, etc.).
        """
        connect_mock = MagicMock(return_value=0)
        return {
            "get_current_user": patch.object(
                toolbox_script,
                "get_current_user",
                return_value={"toolbox-claimed": "user_at_posthog.com"},
            ),
            "get_toolbox_pod": patch.object(toolbox_script, "get_toolbox_pod", return_value=get_pod_returns),
            "claim_pod": patch.object(toolbox_script, "claim_pod"),
            "connect_to_pod": patch.object(toolbox_script, "connect_to_pod", new=connect_mock),
            "delete_pod": patch.object(toolbox_script, "delete_pod"),
            "select_context": patch.object(toolbox_script, "select_context", return_value="posthog-dev"),
            "validate_context": patch.object(toolbox_script, "validate_context", return_value=True),
        }

    def _clean_env(self):
        os.environ.pop("KUBE_CONTEXT", None)
        os.environ.pop("KUBE_NAMESPACE", None)
        os.environ.pop("FLOX_ENV", None)

    def test_main_jumphost_pool_dispatches_correct_kwargs(self):
        """--pool flags-cache-jumphost threads the jumphost app/claim labels into helpers."""
        patches = self._patch_main_collaborators()
        # Override get_current_user for the jumphost pool's claim key.
        patches["get_current_user"] = patch.object(
            toolbox_script,
            "get_current_user",
            return_value={"flags-jumphost-claimed": "user_at_posthog.com"},
        )

        with (
            patches["get_current_user"] as m_user,
            patches["get_toolbox_pod"] as m_get_pod,
            patches["claim_pod"] as m_claim,
            patches["connect_to_pod"],
            patches["delete_pod"],
            patches["select_context"],
            patches["validate_context"],
            patch.object(toolbox_script.sys, "argv", ["toolbox.py", "--pool", "flags-cache-jumphost"]),
            patch.dict(os.environ, {}, clear=False),
        ):
            self._clean_env()
            with self.assertRaises(SystemExit) as ctx:
                toolbox_script.main()
        self.assertEqual(ctx.exception.code, 0)

        m_user.assert_called_once_with(claimed_label_key="flags-jumphost-claimed", context="posthog-dev")
        m_get_pod.assert_called_once_with(
            "user_at_posthog.com",
            check_claimed=True,
            app_label="flags-cache-jumphost",
            claimed_label_key="flags-jumphost-claimed",
            namespace="posthog",
            context="posthog-dev",
        )
        # claim_pod gets namespace, context, and resource_version from get_toolbox_pod's return.
        self.assertEqual(
            m_claim.call_args.kwargs,
            {"namespace": "posthog", "context": "posthog-dev", "resource_version": "12345"},
        )

    def test_main_default_pool_dispatches_toolbox_django_kwargs(self):
        """No --pool argument defaults to toolbox-django and threads its labels."""
        patches = self._patch_main_collaborators()

        with (
            patches["get_current_user"],
            patches["get_toolbox_pod"] as m_get_pod,
            patches["claim_pod"],
            patches["connect_to_pod"],
            patches["delete_pod"],
            patches["select_context"],
            patches["validate_context"],
            patch.object(toolbox_script.sys, "argv", ["toolbox.py"]),
            patch.dict(os.environ, {}, clear=False),
        ):
            self._clean_env()
            with self.assertRaises(SystemExit):
                toolbox_script.main()

        m_get_pod.assert_called_once_with(
            "user_at_posthog.com",
            check_claimed=True,
            app_label="posthog-toolbox-django",
            claimed_label_key="toolbox-claimed",
            namespace="posthog",
            context="posthog-dev",
        )

    def test_main_kube_context_env_validates_without_switching(self):
        """When KUBE_CONTEXT is set, main() validates it and threads it as --context, never calling switch_context."""
        patches = self._patch_main_collaborators()

        with (
            patches["get_current_user"],
            patches["get_toolbox_pod"] as m_get_pod,
            patches["claim_pod"],
            patches["connect_to_pod"],
            patches["delete_pod"],
            patches["select_context"] as m_select,
            patches["validate_context"] as m_validate,
            patch.object(toolbox_script.sys, "argv", ["toolbox.py"]),
            patch.dict(os.environ, {"KUBE_CONTEXT": "posthog-dev"}, clear=False),
        ):
            os.environ.pop("KUBE_NAMESPACE", None)
            os.environ.pop("FLOX_ENV", None)
            with self.assertRaises(SystemExit):
                toolbox_script.main()

        m_validate.assert_called_once_with("posthog-dev")
        m_select.assert_not_called()
        # And the resolved context is threaded into get_toolbox_pod.
        self.assertEqual(m_get_pod.call_args.kwargs["context"], "posthog-dev")

    def test_main_kube_context_unset_falls_back_to_select_context(self):
        """When KUBE_CONTEXT is unset, main() prompts via select_context and uses its return as --context."""
        patches = self._patch_main_collaborators()

        with (
            patches["get_current_user"],
            patches["get_toolbox_pod"] as m_get_pod,
            patches["claim_pod"],
            patches["connect_to_pod"],
            patches["delete_pod"],
            patches["select_context"] as m_select,
            patches["validate_context"] as m_validate,
            patch.object(toolbox_script.sys, "argv", ["toolbox.py"]),
            patch.dict(os.environ, {}, clear=False),
        ):
            self._clean_env()
            with self.assertRaises(SystemExit):
                toolbox_script.main()

        m_select.assert_called_once_with()
        m_validate.assert_not_called()
        self.assertEqual(m_get_pod.call_args.kwargs["context"], "posthog-dev")

    def test_main_kube_context_validate_failure_exits(self):
        """When validate_context returns False, main() exits with status 1."""
        patches = self._patch_main_collaborators()
        patches["validate_context"] = patch.object(toolbox_script, "validate_context", return_value=False)

        with (
            patches["get_current_user"],
            patches["get_toolbox_pod"],
            patches["claim_pod"],
            patches["connect_to_pod"],
            patches["delete_pod"],
            patches["select_context"],
            patches["validate_context"],
            patch.object(toolbox_script.sys, "argv", ["toolbox.py"]),
            patch.dict(os.environ, {"KUBE_CONTEXT": "bogus"}, clear=False),
        ):
            os.environ.pop("FLOX_ENV", None)
            with self.assertRaises(SystemExit) as ctx:
                toolbox_script.main()

        self.assertEqual(ctx.exception.code, 1)

    def test_main_auto_delete_arms_atexit_before_claim_pod(self):
        """atexit.register must run BEFORE claim_pod() so a Ctrl-C during the up-to-5min Ready wait still cleans up."""
        patches = self._patch_main_collaborators()

        parent = MagicMock()

        with (
            patches["get_current_user"],
            patches["get_toolbox_pod"],
            patches["claim_pod"] as m_claim,
            patches["connect_to_pod"],
            patches["delete_pod"],
            patches["select_context"],
            patches["validate_context"],
            patch.object(toolbox_script.atexit, "register") as m_atexit,
            patch.object(toolbox_script.signal, "signal"),
            patch.object(toolbox_script.sys, "argv", ["toolbox.py", "--auto-delete"]),
            patch.dict(os.environ, {}, clear=False),
        ):
            self._clean_env()
            parent.attach_mock(m_atexit, "atexit_register")
            parent.attach_mock(m_claim, "claim_pod")
            with self.assertRaises(SystemExit):
                toolbox_script.main()

        call_names = [name for name, _, _ in parent.mock_calls]
        first_atexit = call_names.index("atexit_register")
        first_claim = call_names.index("claim_pod")
        self.assertLess(first_atexit, first_claim)

    def test_main_auto_delete_registers_signal_handlers_and_atexit(self):
        """--auto-delete registers atexit cleanup and SIGTERM/SIGHUP handlers when claiming a fresh pod."""
        patches = self._patch_main_collaborators()

        with (
            patches["get_current_user"],
            patches["get_toolbox_pod"],
            patches["claim_pod"],
            patches["connect_to_pod"],
            patches["delete_pod"] as m_delete,
            patches["select_context"],
            patches["validate_context"],
            patch.object(toolbox_script.atexit, "register") as m_atexit,
            patch.object(toolbox_script.signal, "signal") as m_signal,
            patch.object(toolbox_script.sys, "argv", ["toolbox.py", "--auto-delete"]),
            patch.dict(os.environ, {}, clear=False),
        ):
            self._clean_env()
            with self.assertRaises(SystemExit):
                toolbox_script.main()

        # atexit cleanup is registered with auto_yes=True, resolved context, and the
        # claim label so delete_pod can verify before deleting an unclaimed pool pod.
        m_atexit.assert_called_once_with(
            m_delete,
            "toolbox-pod-1",
            namespace="posthog",
            context="posthog-dev",
            auto_yes=True,
            expected_label_key="toolbox-claimed",
            expected_label_value="user_at_posthog.com",
        )
        # Both SIGTERM and SIGHUP route to _exit_for_signal.
        signal_calls = {c.args[0]: c.args[1] for c in m_signal.call_args_list}
        self.assertIs(signal_calls[signal.SIGTERM], toolbox_script._exit_for_signal)
        self.assertIs(signal_calls[signal.SIGHUP], toolbox_script._exit_for_signal)

    def test_main_auto_delete_skipped_on_pure_reattach(self):
        """When reattaching to an already-claimed pod (no --update-claim), --auto-delete must NOT register cleanup.

        The pod may still be in active use by another shell of yours; deleting it
        when this shell exits would kill that other session.
        """
        patches = self._patch_main_collaborators(get_pod_returns=("toolbox-pod-1", True, "55555"))

        with (
            patches["get_current_user"],
            patches["get_toolbox_pod"],
            patches["claim_pod"] as m_claim,
            patches["connect_to_pod"],
            patches["delete_pod"],
            patches["select_context"],
            patches["validate_context"],
            patch.object(toolbox_script.atexit, "register") as m_atexit,
            patch.object(toolbox_script.signal, "signal") as m_signal,
            patch.object(toolbox_script.sys, "argv", ["toolbox.py", "--auto-delete"]),
            patch.dict(os.environ, {}, clear=False),
        ):
            self._clean_env()
            with self.assertRaises(SystemExit):
                toolbox_script.main()

        m_atexit.assert_not_called()
        m_signal.assert_not_called()
        m_claim.assert_not_called()  # Pure reattach: no claim mutation either.

    def test_main_auto_delete_armed_when_extending_own_claim(self):
        """--auto-delete WITH --update-claim DOES register cleanup because we are actively (re-)claiming."""
        patches = self._patch_main_collaborators(get_pod_returns=("toolbox-pod-1", True, "55555"))

        with (
            patches["get_current_user"],
            patches["get_toolbox_pod"],
            patches["claim_pod"] as m_claim,
            patches["connect_to_pod"],
            patches["delete_pod"] as m_delete,
            patches["select_context"],
            patches["validate_context"],
            patch.object(toolbox_script.atexit, "register") as m_atexit,
            patch.object(toolbox_script.signal, "signal"),
            patch.object(toolbox_script.sys, "argv", ["toolbox.py", "--auto-delete", "--update-claim"]),
            patch.dict(os.environ, {}, clear=False),
        ):
            self._clean_env()
            with self.assertRaises(SystemExit):
                toolbox_script.main()

        m_atexit.assert_called_once_with(
            m_delete,
            "toolbox-pod-1",
            namespace="posthog",
            context="posthog-dev",
            auto_yes=True,
            expected_label_key="toolbox-claimed",
            expected_label_value="user_at_posthog.com",
        )
        # update-claim path passes resource_version=None because we already own the pod.
        self.assertEqual(m_claim.call_args.kwargs["resource_version"], None)

    def test_main_propagates_connect_to_pod_exit_code(self):
        """When kubectl exec returns non-zero, main() exits with the same code."""
        patches = self._patch_main_collaborators()
        patches["connect_to_pod"] = patch.object(toolbox_script, "connect_to_pod", return_value=42)

        with (
            patches["get_current_user"],
            patches["get_toolbox_pod"],
            patches["claim_pod"],
            patches["connect_to_pod"],
            patches["delete_pod"],
            patches["select_context"],
            patches["validate_context"],
            patch.object(toolbox_script.sys, "argv", ["toolbox.py", "--auto-delete"]),
            patch.dict(os.environ, {}, clear=False),
        ):
            self._clean_env()
            with self.assertRaises(SystemExit) as ctx:
                toolbox_script.main()

        self.assertEqual(ctx.exception.code, 42)

    def test_main_retries_on_claim_race_and_picks_new_pod(self):
        """A ClaimRaceError on the first attempt triggers a re-fetch and retry against the next available pod."""
        patches = self._patch_main_collaborators()
        # Simulate: first get returns pod-A; first claim races; second get returns pod-B; second claim succeeds.
        patches["get_toolbox_pod"] = patch.object(
            toolbox_script,
            "get_toolbox_pod",
            side_effect=[
                ("toolbox-pod-A", False, "1"),
                ("toolbox-pod-B", False, "2"),
            ],
        )
        patches["claim_pod"] = patch.object(
            toolbox_script,
            "claim_pod",
            side_effect=[ClaimRaceError("racing"), None],
        )

        with (
            patches["get_current_user"],
            patches["get_toolbox_pod"] as m_get_pod,
            patches["claim_pod"] as m_claim,
            patches["connect_to_pod"] as m_connect,
            patches["delete_pod"] as m_delete,
            patches["select_context"],
            patches["validate_context"],
            patch.object(toolbox_script.atexit, "register") as m_atexit,
            patch.object(toolbox_script.atexit, "unregister") as m_unregister,
            patch.object(toolbox_script.signal, "signal"),
            patch.object(toolbox_script.sys, "argv", ["toolbox.py", "--auto-delete"]),
            patch.dict(os.environ, {}, clear=False),
        ):
            self._clean_env()
            with self.assertRaises(SystemExit):
                toolbox_script.main()

        self.assertEqual(m_get_pod.call_count, 2)
        self.assertEqual(m_claim.call_count, 2)
        # We connected to the pod we won, not the one we lost.
        m_connect.assert_called_once_with("toolbox-pod-B", namespace="posthog", context="posthog-dev")
        # atexit was registered twice (once per candidate pod) and unregistered once
        # to clear the stale registration after the race.
        self.assertEqual(m_atexit.call_count, 2)
        self.assertEqual(m_unregister.call_count, 1)
        m_unregister.assert_called_with(m_delete)

    def test_main_gives_up_after_max_claim_retries(self):
        """If every attempt races, main() exits 1 rather than looping forever.

        Also asserts that the stale atexit registration is cleared before the
        terminal exit — otherwise atexit would fire delete_pod against an
        unclaimed candidate pod and silently shrink the pool on every
        retry-exhaustion.
        """
        max_retries = toolbox_script.MAX_CLAIM_RETRIES
        patches = self._patch_main_collaborators()
        patches["get_toolbox_pod"] = patch.object(
            toolbox_script,
            "get_toolbox_pod",
            side_effect=[(f"pod-{i}", False, str(i)) for i in range(max_retries + 2)],
        )
        patches["claim_pod"] = patch.object(
            toolbox_script, "claim_pod", side_effect=[ClaimRaceError("racing")] * (max_retries + 1)
        )

        with (
            patches["get_current_user"],
            patches["get_toolbox_pod"],
            patches["claim_pod"] as m_claim,
            patches["connect_to_pod"],
            patches["delete_pod"] as m_delete,
            patches["select_context"],
            patches["validate_context"],
            patch.object(toolbox_script.atexit, "register") as m_atexit,
            patch.object(toolbox_script.atexit, "unregister") as m_unregister,
            patch.object(toolbox_script.signal, "signal"),
            patch.object(toolbox_script.sys, "argv", ["toolbox.py", "--auto-delete"]),
            patch.dict(os.environ, {}, clear=False),
        ):
            self._clean_env()
            with self.assertRaises(SystemExit) as ctx:
                toolbox_script.main()

        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(m_claim.call_count, max_retries)
        # One register for the initial pre-claim arming, one per candidate after
        # each lost race (max_retries - 1 in-loop + 1 final dead candidate when
        # the final claim races) — and one matching unregister per register,
        # including the final one before sys.exit(1).
        self.assertEqual(m_atexit.call_count, m_unregister.call_count)
        self.assertGreaterEqual(m_unregister.call_count, max_retries)
        m_unregister.assert_called_with(m_delete)

    def test_main_race_resolves_to_already_claimed_skips_auto_delete(self):
        """If, after losing a race, the next get_toolbox_pod finds a pod already claimed by us,
        we attach but DO NOT register cleanup against it (it could be another shell's claim)."""
        patches = self._patch_main_collaborators()
        patches["get_toolbox_pod"] = patch.object(
            toolbox_script,
            "get_toolbox_pod",
            side_effect=[
                ("toolbox-pod-A", False, "1"),
                ("toolbox-pod-mine", True, "9"),
            ],
        )
        patches["claim_pod"] = patch.object(
            toolbox_script,
            "claim_pod",
            side_effect=[ClaimRaceError("racing")],
        )

        with (
            patches["get_current_user"],
            patches["get_toolbox_pod"],
            patches["claim_pod"] as m_claim,
            patches["connect_to_pod"] as m_connect,
            patches["delete_pod"] as m_delete,
            patches["select_context"],
            patches["validate_context"],
            patch.object(toolbox_script.atexit, "register") as m_atexit,
            patch.object(toolbox_script.atexit, "unregister") as m_unregister,
            patch.object(toolbox_script.signal, "signal"),
            patch.object(toolbox_script.sys, "argv", ["toolbox.py", "--auto-delete"]),
            patch.dict(os.environ, {}, clear=False),
        ):
            self._clean_env()
            with self.assertRaises(SystemExit):
                toolbox_script.main()

        m_connect.assert_called_once_with("toolbox-pod-mine", namespace="posthog", context="posthog-dev")
        # claim_pod was called once (the racing one) and not retried since we found our own pod.
        self.assertEqual(m_claim.call_count, 1)
        # First atexit register armed cleanup for pod-A; on the race we unregistered;
        # we did NOT re-register for pod-mine.
        self.assertEqual(m_atexit.call_count, 1)
        self.assertEqual(m_unregister.call_count, 1)
        m_unregister.assert_called_with(m_delete)


if __name__ == "__main__":
    unittest.main()
