#!/usr/bin/env python3
"""
Direct entry point for LLM Pro Mode that can be run without installation.
This avoids relative import issues when running the file directly.
"""

import sys
from pathlib import Path

# Add the project root to Python path so we can import the package
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Now we can import and run the main function
from llm_pro_mode.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
