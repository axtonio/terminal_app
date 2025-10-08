from ..root import Root

class Child(Root):
    LOGGING = True
    
    def __init__(self) -> None:
        self.logger.info("Child init...")
        self.root_logger.info("Child init...")
        
Child()