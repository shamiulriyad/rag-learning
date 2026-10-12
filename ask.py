"""Query pipeline - steps 7 to 11. Shortcut for `python cli.py ask`.

    python ask.py "what is the refund policy?"
    python ask.py                 # interactive loop, 'exit' to quit
"""

import sys

import cli

if __name__ == "__main__":
    sys.exit(cli.main(["ask", *sys.argv[1:]]))
