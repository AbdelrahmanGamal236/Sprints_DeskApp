"""Entry point of DeskAppServer.exe: the Central Server with a console window."""
import sys

import main

if __name__ == "__main__":
    args = sys.argv[1:]
    if not {"--server-only", "--restore", "--version", "--reset-superadmin"} & set(args):
        args.append("--server-only")
    main.main(args)
