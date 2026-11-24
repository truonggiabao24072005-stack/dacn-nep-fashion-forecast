"""Cleanup requires an exact generated database name and its ownership marker."""

import sys

from manage_database import main

if __name__ == "__main__":
    main(["cleanup", *sys.argv[1:]])
