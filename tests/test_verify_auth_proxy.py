"""Check that the local proxy verifier cannot pass with a failed cleanup."""

import contextlib
import io
import subprocess
import unittest
from unittest.mock import Mock, patch

from scripts import verify_auth_proxy as verifier


class ProxyVerifierCleanupTests(unittest.TestCase):
    """Use synthetic command outcomes without touching Docker resources."""

    def test_failed_compose_cleanup_is_a_verification_failure(self):
        """A failed down command identifies the isolated project and exits nonzero."""
        project = "usc-proxy-test-0123456789ab"
        run = Mock(side_effect=subprocess.CalledProcessError(1, ["docker"]))
        output = io.StringIO()
        with patch.object(verifier, "verify", side_effect=lambda: verifier.cleanup(run, project)):
            with contextlib.redirect_stdout(output):
                self.assertEqual(verifier.main(), 1)
        run.assert_called_once_with("down", "--volumes")
        self.assertIn(project, output.getvalue())
        self.assertIn("label=com.docker.compose.project=", output.getvalue())
        self.assertNotIn("PASS", output.getvalue())

    def test_missing_image_after_successful_cleanup_is_normal(self):
        """Cleanup tolerates a run that did not reach the image build."""
        run = Mock()
        with patch.object(verifier.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 0, stdout="")) as docker:
            verifier.cleanup(run, "usc-proxy-test-0123456789ab")
        run.assert_called_once_with("down", "--volumes")
        docker.assert_called_once()

    def test_image_removal_timeout_reports_project(self):
        """A disposable image cleanup timeout prevents a pass."""
        listing = subprocess.CompletedProcess([], 0, stdout="fixture-image-id")
        timeout = subprocess.TimeoutExpired(["docker"], 30)
        with patch.object(verifier.subprocess, "run", side_effect=[listing, timeout]):
            with self.assertRaisesRegex(verifier.CleanupError, "usc-proxy-test-0123456789ab"):
                verifier.cleanup(Mock(), "usc-proxy-test-0123456789ab")
