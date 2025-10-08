from pathlib import Path
import sys

sys.path.append(Path(__file__).parent.parent.parent.parent.as_posix())

from terminal_app.logging import register_logger

logger = register_logger()

if __name__ == "__main__":
    print("Test 1...")
    import root
    
    logger.info("Logger")
    
    assert (Path(__file__).parent / "loggers/root_root.log").exists()
    assert (Path(__file__).parent / "root/root.log").exists()
    assert (Path(__file__).parent / "root/child/child.log").exists()
    
    