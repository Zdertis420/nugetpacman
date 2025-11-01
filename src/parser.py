import requests
import json
import re
from urllib.parse import urlencode


def get_nuget_service_index():
    """
    Fetch the NuGet V3 service index.
    """
    url = "https://api.nuget.org/v3/index.json"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def find_resource_url(service_index, resource_type):
    """
    Find the URL for a specific resource type in the service index.
    """
    for resource in service_index["resources"]:
        if resource["@type"] == resource_type:
            return resource["@id"]
    raise ValueError(f"Resource type '{resource_type}' not found.")


def search_packages(query, take=10, skip=0):
    """
    Search for packages using the NuGet SearchQueryService.

    :param query: The search query string.
    :param take: Number of results to return.
    :param skip: Number of results to skip (for pagination).
    :return: List of package metadata.
    """
    service_index = get_nuget_service_index()
    search_url = find_resource_url(service_index, "SearchQueryService")

    params = {"q": query, "take": take, "skip": skip}
    url = f"{search_url}?{urlencode(params)}"

    response = requests.get(url)
    response.raise_for_status()
    data = response.json()
    return data["data"]


def get_package_versions(package_id):
    """
    Get all versions of a specific package using the RegistrationsBaseUrl.

    :param package_id: The ID of the package (case-insensitive).
    :return: List of versions.
    """
    service_index = get_nuget_service_index()
    registrations_url = find_resource_url(service_index, "RegistrationsBaseUrl")

    # Package IDs are lowercased in the URL
    package_id_lower = package_id.lower()
    index_url = f"{registrations_url}{package_id_lower}/index.json"

    response = requests.get(index_url)
    response.raise_for_status()
    index_data = response.json()

    versions = []
    pages = index_data.get("items", [])

    for page in pages:
        if "items" in page:
            # Inline items
            for entry in page["items"]:
                catalog_entry = entry.get("catalogEntry")
                if isinstance(catalog_entry, dict):
                    version = catalog_entry.get("version")
                    if version:
                        versions.append(version)
                elif isinstance(catalog_entry, str):
                    # If catalogEntry is a URL, fetch it
                    cat_response = requests.get(catalog_entry)
                    cat_response.raise_for_status()
                    cat_data = cat_response.json()
                    version = cat_data.get("version")
                    if version:
                        versions.append(version)
        else:
            # Fetch the page
            page_url = page["@id"]
            page_response = requests.get(page_url)
            page_response.raise_for_status()
            page_data = page_response.json()
            for entry in page_data.get("items", []):
                catalog_entry = entry.get("catalogEntry")
                if isinstance(catalog_entry, dict):
                    version = catalog_entry.get("version")
                    if version:
                        versions.append(version)
                elif isinstance(catalog_entry, str):
                    # If catalogEntry is a URL, fetch it
                    cat_response = requests.get(catalog_entry)
                    cat_response.raise_for_status()
                    cat_data = cat_response.json()
                    version = cat_data.get("version")
                    if version:
                        versions.append(version)

    return versions


def get_package_dependencies(package_id, version):
    """
    Get the direct dependencies for a specific package version using the RegistrationsBaseUrl.

    :param package_id: The ID of the package (case-insensitive).
    :param version: The version of the package (case-insensitive).
    :return: List of dependencies, each as a dict with 'framework', 'id', and 'range'.
    """
    service_index = get_nuget_service_index()
    registrations_url = find_resource_url(service_index, "RegistrationsBaseUrl")

    package_id_lower = package_id.lower()
    version_lower = version.lower()  # Versions are normalized to lowercase in URLs
    leaf_url = f"{registrations_url}{package_id_lower}/{version_lower}.json"

    response = requests.get(leaf_url)
    response.raise_for_status()
    data = response.json()

    catalog_entry = data.get("catalogEntry")
    if isinstance(catalog_entry, str):
        # Fetch the catalog entry if it's a URL
        catalog_response = requests.get(catalog_entry)
        catalog_response.raise_for_status()
        catalog_entry = catalog_response.json()
    elif not isinstance(catalog_entry, dict):
        raise ValueError("Unexpected type for catalogEntry")

    dependency_groups = catalog_entry.get("dependencyGroups", [])

    dependencies = []
    for group in dependency_groups:
        target_framework = group.get("targetFramework", "Any")
        deps = group.get("dependencies", [])
        for dep in deps:
            dep_id = dep.get("id")
            dep_range = dep.get("range", "*")
            dependencies.append(
                {"framework": target_framework, "id": dep_id, "range": dep_range}
            )
    return dependencies


def version_to_key(v):
    """
    Convert a version string to a sortable key, handling semantic versioning.
    """
    if v is None:
        return ((), (0,), ())  # None sorts low
    v = v.lower().strip()
    match = re.match(r"^(\d+(?:\.\d+)*)(?:-([^+]+))?(?:\+(.*))?$", v)
    if not match:
        return ((), (0,), ())  # Invalid versions sort low
    core_str, pre_str, build_str = match.groups()
    core_parts = tuple(int(x) for x in core_str.split(".") if x)
    if pre_str:
        pre_parts = []
        for p in pre_str.split("."):
            if p.isdigit():
                pre_parts.append((0, int(p)))
            else:
                pre_parts.append((1, p))
        pre_key = (0,) + tuple(pre_parts)
    else:
        pre_key = (1,)
    build_key = tuple(build_str.split(".")) if build_str else ()
    return (core_parts, pre_key, build_key)


def print_dependency_tree(
    package_id,
    version,
    framework=None,
    indent="",
    visited=None,
    current_depth=0,
    max_depth=5,
):
    """
    Print the dependency tree recursively, using the latest version for each dependency.

    :param package_id: The ID of the package.
    :param version: The version of the package.
    :param framework: Optional target framework to filter dependencies.
    :param indent: Indentation string for tree structure.
    :param visited: Set to track visited packages to avoid cycles.
    :param current_depth: Current recursion depth.
    :param max_depth: Maximum recursion depth to prevent too deep trees.
    """
    if visited is None:
        visited = set()

    key = f"{package_id.lower()}.{version.lower()}"
    if key in visited or current_depth > max_depth:
        if current_depth > max_depth:
            print(indent + f"{package_id} {version} (max depth reached)")
        else:
            print(indent + f"{package_id} {version} (cycle detected)")
        return

    visited.add(key)

    print(indent + f"{package_id} {version}")

    direct_deps = get_package_dependencies(package_id, version)

    if framework:
        direct_deps = [
            d
            for d in direct_deps
            if d["framework"] == framework or d["framework"] == "Any"
        ]

    for dep in direct_deps:
        dep_id = dep["id"]
        versions = get_package_versions(dep_id)
        if not versions:
            print(indent + "  " + f"{dep_id} (no versions found)")
            continue

        # Sort versions to find the latest
        versions.sort(key=version_to_key, reverse=True)
        latest_ver = versions[0]

        # Note: This uses the latest version, but in practice, you should resolve based on the range.
        print_dependency_tree(
            dep_id,
            latest_ver,
            framework,
            indent + "  ",
            visited,
            current_depth + 1,
            max_depth,
        )


# Example usage
if __name__ == "__main__":
    # Search for packages
    print("Searching for 'Newtonsoft.Json':")
    results = search_packages("Newtonsoft.Json", take=1)
    for pkg in results:
        print(
            f"Package: {pkg['id']}, Version: {pkg['version']}, Description: {pkg['description']}"
        )

    # Get versions
    print("\nVersions of 'Newtonsoft.Json':")
    versions = get_package_versions("Newtonsoft.Json")
    print(versions)

    # Get dependencies (using the version from search, which is typically the latest)
    if results:
        pkg = results[0]
        print(f"\nDependencies for {pkg['id']} version {pkg['version']}:")
        deps = get_package_dependencies(pkg["id"], pkg["version"])
        if deps:
            for dep in deps:
                print(
                    f"Framework: {dep['framework']}, ID: {dep['id']}, Range: {dep['range']}"
                )
        else:
            print("No dependencies found.")

        # Print dependency tree
        # Note: Newtonsoft.Json has no dependencies, so the tree will be simple.
        # For a package with dependencies, replace with e.g., 'NuGet.Commands' or 'Microsoft.EntityFrameworkCore'
        print("\nDependency tree:")
        print_dependency_tree(pkg["id"], pkg["version"])
