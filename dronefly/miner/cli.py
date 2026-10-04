import argparse
from dronefly.miner.fts import load_fts_data

def build():
    load_fts_data()

def main():
    parser = argparse.ArgumentParser(prog="dronefly-miner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("build", help="Load FTS taxa into the database for all languages.")
    args = parser.parse_args()

    if args.command == "build":
        build()

if __name__ == "__main__":
    main()