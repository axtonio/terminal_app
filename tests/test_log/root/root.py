from terminal_app.logging import RootLogging
import os

os.environ["ROOT_LOGGING"] = "1"


class Root(RootLogging):
    LOGGING = True
    
    def __init__(self) -> None:
        self.logger.info("Root init...")
        self.root_logger.info("Root init...")

        
Root()