from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    policy_path: Path
    agent_token: str
    admin_token: str
    github_app_id: str
    github_installation_id: str
    github_private_key_path: Path | None
    github_webhook_secret: str

    @property
    def database_path(self) -> Path:
        return self.data_dir / "changewarden.sqlite"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("CHANGEWARDEN_DATA_DIR", "./data")).resolve()
        policy_path = Path(os.environ.get("CHANGEWARDEN_POLICY_PATH", "./policy.yaml")).resolve()
        key_path = os.environ.get("CHANGEWARDEN_GITHUB_PRIVATE_KEY_PATH", "").strip()
        return cls(
            data_dir=data_dir,
            policy_path=policy_path,
            agent_token=os.environ.get("CHANGEWARDEN_AGENT_TOKEN", "").strip(),
            admin_token=os.environ.get("CHANGEWARDEN_ADMIN_TOKEN", "").strip(),
            github_app_id=os.environ.get("CHANGEWARDEN_GITHUB_APP_ID", "").strip(),
            github_installation_id=os.environ.get("CHANGEWARDEN_GITHUB_INSTALLATION_ID", "").strip(),
            github_private_key_path=Path(key_path).resolve() if key_path else None,
            github_webhook_secret=os.environ.get("CHANGEWARDEN_GITHUB_WEBHOOK_SECRET", "").strip(),
        )
