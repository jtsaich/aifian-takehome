"""scripts/deploy.sh in DRY_RUN mode: the deploy contract without touching Google Cloud."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "deploy.sh"
NEON_URL = "postgresql://app:s3cret-pw@ep-x.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"


def deploy(**env: str) -> subprocess.CompletedProcess[str]:
    base = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), "DRY_RUN": "1"}
    return subprocess.run(
        ["bash", str(SCRIPT)], env={**base, **env}, capture_output=True, text=True, check=False
    )


def command_line(out: str, *needles: str) -> str:
    matches = [line for line in out.splitlines() if all(n in line for n in needles)]
    assert len(matches) == 1, (needles, out)
    return matches[0]


def test_deploys_service_to_taiwan_scaling_to_zero_with_secret_references() -> None:
    result = deploy(GCP_PROJECT="demo-proj", DATABASE_URL=NEON_URL, SESSION_SECRET="k" * 64)

    assert result.returncode == 0, result.stderr
    service = command_line(result.stdout, "run deploy")
    assert "--region asia-east1" in service
    assert "--min-instances 0" in service
    assert "--allow-unauthenticated" in service
    assert "BAKERY_ENV=production,PUBLIC_BASE_URL=https://bakery-orders-" in service
    secrets = "DATABASE_URL=bakery-database-url:latest,SESSION_SECRET=bakery-session-secret:latest"
    assert f"--set-secrets {secrets}" in service
    # Secret values only travel through Secret Manager, never on a command line.
    assert "s3cret-pw" not in result.stdout + result.stderr
    assert "k" * 64 not in result.stdout + result.stderr


def test_migrates_with_a_job_before_the_service_is_deployed() -> None:
    result = deploy(GCP_PROJECT="demo-proj", DATABASE_URL=NEON_URL)

    assert result.returncode == 0, result.stderr
    job = command_line(result.stdout, "run jobs deploy")
    assert "--command bakery-init" in job
    assert "--execute-now --wait" in job
    lines = result.stdout.splitlines()
    assert lines.index(job) < lines.index(command_line(result.stdout, "run deploy"))


def test_refuses_a_database_url_without_tls() -> None:
    result = deploy(
        GCP_PROJECT="demo-proj",
        DATABASE_URL="postgresql://app:pw@ep-x.ap-southeast-1.aws.neon.tech/neondb",
    )

    assert result.returncode != 0
    assert "sslmode=require" in result.stderr
    assert "gcloud" not in result.stdout


def test_requires_the_database_url_on_first_deploy() -> None:
    result = deploy(GCP_PROJECT="demo-proj")

    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr
