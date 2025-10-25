import argparse
import os
from pathlib import Path
import sys
import yaml

CONFIG_DIR_NAME = ".config"
TOOL_DIR_NAME = "dependency-tool"
CONFIG_FILE_NAME = "config.yaml"

CONFIG_PATH = Path.home() / CONFIG_DIR_NAME / TOOL_DIR_NAME / CONFIG_FILE_NAME


def initialize_config():
    config_file_path = CONFIG_PATH
    config_dir_path = config_file_path.parent

    if not config_dir_path.exists():
        print(f"Config dir not found: {config_dir_path}")
        try:
            config_dir_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(
                f"Error: Could not create config dir: {e}",
                file=sys.stderr,
            )
            return

    else:
        print(f"Config dir exists: {config_dir_path}")

    if not config_file_path.exists():
        print(f"Config not found: {CONFIG_FILE_NAME}")
        try:
            config_file_path.touch(exist_ok=True)
        except OSError as e:
            print(f"Error: Could not create config file: {e}", file=sys.stderr)


def load_config():
    config_path = CONFIG_PATH

    if not config_path.exists():
        print(
            "Error: Config file not found.\nCreate new by running with init argument."
        )
        return

    with open(config_path) as stream:
        try:
            config = yaml.safe_load(stream)

            print("=== Current config ===")
            for i, j in config.items():
                print(f"{i}: {j}")
            print("=== END ===")
        except yaml.YAMLError as err:
            print(err)


def main():
    """
    Основная функция для запуска CLI.
    """
    parser = argparse.ArgumentParser(
        description="Tool for dependency graph analysis and visualization."
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    parser_init = subparsers.add_parser(
        "init", help="Initializes the configuration directory and file."
    )

    subparsers.add_parser(
        "deps", help="Finds direct and transitive dependencies for a given package."
    )
    subparsers.add_parser(
        "rdeps",
        help="Finds packages that depend on the given package (reverse dependencies).",
    )
    subparsers.add_parser(
        "visualize",
        help="Generates PlantUML/SVG or ASCII-tree visualization of the graph.",
    )

    args = parser.parse_args()

    load_config()

    match args.command:
        case "init":
            initialize_config()
        case None:
            parser.print_help()
        case _:
            print(
                f"Tool running in {args.command.upper()} mode. Command logic coming soon."
            )


if __name__ == "__main__":
    main()
