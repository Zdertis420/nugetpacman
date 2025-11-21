import requests
import json
import re
from urllib.parse import urlencode
from collections import deque


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

    package_id_lower = package_id.lower()
    index_url = f"{registrations_url}{package_id_lower}/index.json"

    response = requests.get(index_url)
    response.raise_for_status()
    index_data = response.json()

    versions = []
    pages = index_data.get("items", [])

    for page in pages:
        page_items = page.get("items")
        if not page_items:
            try:
                page_response = requests.get(page["@id"])
                page_response.raise_for_status()
                page_data = page_response.json()
                page_items = page_data.get("items", [])
            except requests.RequestException:
                continue

        for entry in page_items:
            catalog_entry = entry.get("catalogEntry")
            if isinstance(catalog_entry, dict):
                version = catalog_entry.get("version")
                if version:
                    versions.append(version)
            elif "version" in entry:
                versions.append(entry["version"])

    return sorted(list(set(versions)), key=version_to_key, reverse=True)


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

    try:
        response = requests.get(leaf_url)
        if response.status_code == 404:
            index_url = f"{registrations_url}{package_id_lower}/index.json"
            idx_resp = requests.get(index_url)
            idx_resp.raise_for_status()
            idx_data = idx_resp.json()
            for page in idx_data.get("items", []):
                for item in page.get("items", []):
                    if (
                        item.get("catalogEntry", {}).get("version", "").lower()
                        == version_lower
                    ):
                        catalog_url = item.get("catalogEntry", {}).get("@id")
                        if catalog_url:
                            response = requests.get(catalog_url)
                            break
                if response.status_code == 200:
                    break
            if response.status_code == 404:
                response.raise_for_status()

        response.raise_for_status()
        data = response.json()

        if "dependencyGroups" in data:
            catalog_entry = data
        elif "catalogEntry" in data:
            catalog_entry_url_or_data = data.get("catalogEntry")
            if isinstance(catalog_entry_url_or_data, str):
                catalog_response = requests.get(catalog_entry_url_or_data)
                catalog_response.raise_for_status()
                catalog_entry = catalog_response.json()
            elif isinstance(catalog_entry_url_or_data, dict):
                catalog_entry = catalog_entry_url_or_data
            else:
                raise ValueError("Unexpected type for catalogEntry")
        else:
            catalog_entry = {}

    except requests.RequestException as e:
        print(
            f"  [Error] Не удалось получить зависимости для {package_id} {version}: {e}"
        )
        return []

    dependency_groups = catalog_entry.get("dependencyGroups", [])

    dependencies = []
    for group in dependency_groups:
        target_framework = group.get("targetFramework", "Any")
        deps = group.get("dependencies", [])
        for dep in deps:
            dep_id = dep.get("id")
            if not dep_id:
                continue
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
        return ((), (0,), ())
    v = v.lower().strip()
    match = re.match(r"^(\d+(?:\.\d+)*)(?:-([^+]+))?(?:\+(.*))?$", v)
    if not match:
        return ((), (0,), ())
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


def build_dependency_graph_dfs(
    start_package, start_version, framework=None, exclude_substring=None
):
    """
    Построение графа зависимостей с использованием нерекурсивного DFS (обход в глубину).

    :param start_package: Корневой пакет.
    :param start_version: Версия корневого пакета.
    :param framework: (Опционально) Целевой фреймворк для фильтрации зависимостей.
    :param exclude_substring: (Опционально) Подстрока для исключения пакетов из анализа.
    :return: Словарь (граф), представляющий список смежности.
    """

    print(f"Начало построения графа для: {start_package} v{start_version}")

    if exclude_substring:
        exclude_substring = exclude_substring.lower()
        print(f"Исключаем пакеты, содержащие: '{exclude_substring}'")

        if exclude_substring in start_package.lower():
            print(f"Корневой пакет {start_package} исключен из анализа.")
            return {}

    stack = deque([(start_package, start_version)])

    graph = {}

    visited = set()

    while stack:
        try:
            current_id, current_version = stack.pop()
            current_id_lower = current_id.lower()

            if current_id_lower in visited:
                continue

            visited.add(current_id_lower)

            if current_id not in graph:
                graph[current_id] = set()

            print(f"  Анализ: {current_id} v{current_version}")

            direct_deps = get_package_dependencies(current_id, current_version)

            if framework:
                deps_to_process = [
                    d
                    for d in direct_deps
                    if d["framework"].lower() == framework.lower()
                    or d["framework"] == "Any"
                ]
            else:
                deps_to_process = direct_deps

            for dep in deps_to_process:
                dep_id = dep["id"]
                dep_id_lower = dep_id.lower()

                if exclude_substring and exclude_substring in dep_id_lower:
                    print(f"    -> Пропуск (фильтр): {dep_id}")
                    continue

                graph[current_id].add(dep_id)

                if dep_id_lower not in visited:
                    versions = get_package_versions(dep_id)
                    if not versions:
                        print(f"    -> {dep_id} (версии не найдены)")
                        continue

                    latest_ver = versions[0]
                    stack.append((dep_id, latest_ver))

        except requests.RequestException as e:
            print(f"  [Error] Ошибка при обработке {current_id}: {e}")
        except Exception as e:
            print(f"  [Fatal Error] Непредвиденная ошибка с {current_id}: {e}")

    print("Построение графа завершено.")
    return graph


def get_reverse_dependencies(package_id, skip=0, take=100):
    """
    Get the direct reverse dependencies (packages that depend on this one) using the undocumented NuGet dependents API.

    :param package_id: The ID of the package (case-insensitive).
    :param skip: Number of results to skip (for pagination).
    :param take: Number of results to return.
    :return: List of dependent package IDs.
    """
    package_id = package_id  # Case-sensitive as per API
    params = {
        "packageId": package_id,
        "projectType": "nuget",
        "skip": skip,
        "take": take,
    }
    url = f"https://api.nuget.org/v3/dependents?{urlencode(params)}"

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])
    except requests.RequestException as e:
        print(
            f"  [Error] Не удалось получить обратные зависимости для {package_id}: {e}"
        )
        return []


def build_reverse_dependency_graph_dfs(
    start_package, exclude_substring=None, max_dependents_per_package=100
):
    """
    Построение графа обратных зависимостей с использованием нерекурсивного DFS (обход в глубину).
    Граф представляет пакеты, которые зависят от данного (dependents).

    :param start_package: Корневой пакет.
    :param exclude_substring: (Опционально) Подстрока для исключения пакетов из анализа.
    :param max_dependents_per_package: Максимальное количество прямых dependents на пакет (для ограничения, так как может быть тысячи).
    :return: Словарь (граф), где ключ - пакет, значение - set dependents.
    """

    print(f"Начало построения графа обратных зависимостей для: {start_package}")

    if exclude_substring:
        exclude_substring = exclude_substring.lower()
        print(f"Исключаем пакеты, содержащие: '{exclude_substring}'")

        if exclude_substring in start_package.lower():
            print(f"Корневой пакет {start_package} исключен из анализа.")
            return {}

    stack = deque([start_package])

    graph = {}

    visited = set()

    while stack:
        try:
            current_id = stack.pop()
            current_id_lower = current_id.lower()

            if current_id_lower in visited:
                continue

            visited.add(current_id_lower)

            if current_id not in graph:
                graph[current_id] = set()

            print(f"  Анализ обратных зависимостей: {current_id}")

            # Получаем только первые max_dependents_per_package (без пагинации дальше, чтобы избежать перегрузки)
            direct_dependents = get_reverse_dependencies(
                current_id, skip=0, take=max_dependents_per_package
            )

            for dep_id in direct_dependents:
                dep_id_lower = dep_id.lower()

                if exclude_substring and exclude_substring in dep_id_lower:
                    print(f"    -> Пропуск (фильтр): {dep_id}")
                    continue

                graph[current_id].add(dep_id)

                if dep_id_lower not in visited:
                    stack.append(dep_id)

        except requests.RequestException as e:
            print(f"  [Error] Ошибка при обработке {current_id}: {e}")
        except Exception as e:
            print(f"  [Fatal Error] Непредвиденная ошибка с {current_id}: {e}")

    print("Построение графа обратных зависимостей завершено.")
    return graph


def print_graph(graph):
    """
    Аккуратно выводит граф зависимостей.
    """
    if not graph:
        print("Граф пуст.")
        return

    print("\n--- Граф зависимостей (Пакет -> [Зависимости]) ---")
    for package, dependencies in sorted(graph.items()):
        print(f"\n{package}:")
        if dependencies:
            for dep in sorted(list(dependencies)):
                print(f"  -> {dep}")
        else:
            print("  (нет зависимостей)")
    print("--------------------------------------------------")


if __name__ == "__main__":
    START_PACKAGE = "Newtonsoft.Json"
    FRAMEWORK_FILTER = None
    EXCLUDE_FILTER = None

    print(f"Ищем последнюю версию для {START_PACKAGE}...")
    try:
        versions = get_package_versions(START_PACKAGE)
        if not versions:
            print("Не удалось найти версии.")
            exit()

        latest_version = versions[0]
        print(f"Найдена версия: {latest_version}")

        dependency_graph = build_dependency_graph_dfs(
            START_PACKAGE,
            latest_version,
            framework=FRAMEWORK_FILTER,
            exclude_substring=EXCLUDE_FILTER,
        )

        print_graph(dependency_graph)

        print("\n\n--- БЕЗ ФИЛЬТРАЦИИ ---")

        dependency_graph_full = build_dependency_graph_dfs(
            START_PACKAGE,
            latest_version,
            framework=FRAMEWORK_FILTER,
            exclude_substring=None,
        )
        print_graph(dependency_graph_full)

        print("\n\n--- ГРАФ ОБРАТНЫХ ЗАВИСИМОСТЕЙ ---")

        reverse_dependency_graph = build_reverse_dependency_graph_dfs(
            START_PACKAGE,
            exclude_substring=EXCLUDE_FILTER,
        )
        print_graph(reverse_dependency_graph)

    except requests.RequestException as e:
        print(f"\nОшибка API: {e}")
    except ValueError as e:
        print(f"\nОшибка данных: {e}")
