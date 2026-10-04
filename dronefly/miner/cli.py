import argparse
from dronefly.miner.fts import load_fts_data

def build(full: bool = False):
    load_fts_data(full)

def main():
    parser = argparse.ArgumentParser(prog="dronefly-miner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    build_parser = subparsers.add_parser("build", help="Load FTS taxa into the database for all languages.")
    build_parser.add_argument(
        "--full",
        action="store_true",
        help="Perform a full build including heavy observation datasets."
    )
    
    args = parser.parse_args()

    if args.command == "build":
        build(full=args.full)

if __name__ == "__main__":
    main()
