from pathlib import Path
from terminal_app.env import source, ProjectConfig


class MyProject(ProjectConfig):

    CERTIFICATES_DIR: Path = Path("certs")
    SSH_DIR: Path = CERTIFICATES_DIR / "ssh"

    DATA_DIR: Path = Path("data")
    TMP_DIR: Path = DATA_DIR / "tmp"
    CACHE_DIR: Path = DATA_DIR / "cache"
    BACKUP_DIR: Path = DATA_DIR / "backup"
    EXAMPLES_DIR: Path = DATA_DIR / "examples"

    MEDIA_DIR: Path = DATA_DIR / "media"
    DOCUMENT_DIR: Path = MEDIA_DIR / "document"
    VIDEO_DIR: Path = MEDIA_DIR / "video"
    PHOTO_DIR: Path = MEDIA_DIR / "photo"

    MODES: list[str] = ["a", "b", "c"]


PROJECT_CONFIG = MyProject()

print(source(".test_global.json"))
print(source(".test_global.yaml"))
print(source(".test_global.env"))
print(source(".openai.yaml"))
