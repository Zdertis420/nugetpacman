import argparse
import os
from pathlib import Path
import sys
import yaml
import json
import urllib.request
from urllib.error import HTTPError, URLError

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
        return None

    with open(config_path) as stream:
        try:
            config = yaml.safe_load(stream)

            print("=== Current config ===")
            if config:
                for i, j in config.items():
                    print(f"{i}: {j}")
            else:
                print("(Config file is empty)")
            print("=== END ===")
            return config
        except yaml.YAMLError as err:
            print(err)
            return None


def find_dependencies(package_name, package_version):
    """
    Получает и отображает прямые зависимости для указанной версии пакета NuGet.
    """
    NUGET_INDEX_URL = "https://api.nuget.org/v3/index.json"

    try:
        print(f"Fetching NuGet service index...")
        with urllib.request.urlopen(NUGET_INDEX_URL) as response:
            index_data = json.loads(response.read())

        registrations_base_url = None
        for resource in index_data["resources"]:
            if resource["@type"].startswith("RegistrationsBaseUrl"):
                registrations_base_url = resource["@id"]
                break

        if not registrations_base_url:
            print(
                "Error: Could not find 'RegistrationsBaseUrl' in NuGet service index.",
                file=sys.stderr,
            )
            return

        package_id_lower = package_name.lower()
        registration_url = f"{registrations_base_url}{package_id_lower}/index.json"
        print(f"Fetching package registration index: {registration_url}")

        with urllib.request.urlopen(registration_url) as response:
            registration_data = json.loads(response.read())

        page_url = None
        for page in registration_data["items"]:
            if page.get("lower") <= package_version <= page.get("upper"):
                page_url = page["@id"]
                break

        if not page_url:
            print(
                f"Error: Could not find package version {package_version} in registration index.",
                file=sys.stderr,
            )
            return

        print(f"Fetching metadata page: {page_url}")
        with urllib.request.urlopen(page_url) as response:
            page_data = json.loads(response.read())

        catalog_entry = None
        for item in page_data.get("items", []):
            entry = item.get("catalogEntry", {})
            if entry.get("version") == package_version:
                catalog_entry = entry
                break

        if not catalog_entry:
            print(
                f"Error: Could not find catalog entry for version {package_version} in metadata page.",
                file=sys.stderr,
            )
            return

        print(f"\n=== Direct Dependencies for {package_name} {package_version} ===")

        dependency_groups = catalog_entry.get("dependencyGroups")

        if not dependency_groups:
            print("No dependencies listed for this package version.")
            print("=== END ===")
            return

        for group in dependency_groups:
            target_framework = group.get("targetFramework", "All Frameworks")
            print(f"\n  Target Framework: {target_framework}")

            dependencies = group.get("dependencies")
            if not dependencies:
                print("    (No dependencies for this framework)")
                continue

            for dep in dependencies:
                dep_id = dep.get("id")
                dep_range = dep.get("range")
                print(f"    - {dep_id} (Version: {dep_range})")

        print("=== END ===")

    except HTTPError as e:
        print(f"Error: HTTP request failed: {e.code} {e.reason}", file=sys.stderr)
        if e.code == 404:
            print(
                f"Package '{package_name}' or version '{package_version}' not found.",
                file=sys.stderr,
            )
    except URLError as e:
        print(f"Error: Could not reach NuGet server: {e.reason}", file=sys.stderr)
    except json.JSONDecodeError:
        print(
            "Error: Failed to parse JSON response from NuGet server.", file=sys.stderr
        )
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Tool for dependency graph analysis and visualization."
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    parser_init = subparsers.add_parser(
        "init", help="Initializes the configuration directory and file."
    )

    parser_deps = subparsers.add_parser(
        "deps", help="Finds direct dependencies for a given package."
    )
    parser_deps.add_argument("package_name", help="Name of the NuGet package")
    parser_deps.add_argument("package_version", help="Version of the NuGet package")

    subparsers.add_parser(
        "rdeps",
        help="Finds packages that depend on the given package (reverse dependencies).",
    )
    subparsers.add_parser(
        "visualize",
        help="Generates PlantUML/SVG or ASCII-tree visualization of the graph.",
    )

    args = parser.parse_args()

    if args.command == "init":
        initialize_config()
        return  # Выход после инициализации

    config = load_config()
    if config is None:
        print("Config not loaded. Run 'init' or check config file.", file=sys.stderr)
        return

    match args.command:
        case "deps":
            find_dependencies(args.package_name, args.package_version)
        case "rdeps":
            print(
                f"Tool running in {args.command.upper()} mode. Command logic coming soon."
            )
        case "visualize":
            print(
                f"Tool running in {args.command.upper()} mode. Command logic coming soon."
            )
        case None:
            parser.print_help()
        case _:
            print(f"Unknown command: {args.command}", file=sys.stderr)


if __name__ == "__main__":
    main()
