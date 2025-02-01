from terminal_app.env import source, PROJECT_CONFIG
from terminal_app.logging import register_logger

print(PROJECT_CONFIG.CERTIFICATES_DIR)
register_logger(name="lol", library=True)
source(".terminal.env")["ANY"]
source(".terminal_lol.env")["ANY"]
config = source(".terminal_ap.env")
print(config["LOL"])
