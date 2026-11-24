#!/usr/bin/env python3
"""校验 registry.json 的结构与字段约束。

仅使用 Python 标准库，可在本地与 GitHub Actions 直接运行：
    python3 scripts/validate.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "registry.json"

TOP_LEVEL_KEYS = {"schema", "generatedAt", "plugins"}
PLUGIN_KEYS = {
    "pluginId",
    "name",
    "version",
    "artifactType",
    "applicationId",
    "versionCode",
    "url",
    "sha256",
    "signerSha256",
    "minHostVersion",
    "pluginSdkVersion",
    "capabilities",
    "repo",
    "sizeBytes",
}
OPTIONAL_KEYS = {"applicationId", "versionCode", "sizeBytes"}
REQUIRED_KEYS = PLUGIN_KEYS - OPTIONAL_KEYS
ARTIFACT_TYPES = {"apk", "lhplugin"}

PLUGIN_ID = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$")
VERSION = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
HTTPS_URL = re.compile(r"^https://\S+$")
CAPABILITY = re.compile(r"^[a-z][a-z0-9._-]*$")


def is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_plugin(index: int, plugin: object, seen: set[str]) -> list[str]:
    prefix = f"plugins[{index}]"
    if not isinstance(plugin, dict):
        return [f"{prefix} 必须是 JSON 对象"]

    errors: list[str] = []
    unknown = sorted(set(plugin) - PLUGIN_KEYS)
    if unknown:
        errors.append(f"{prefix} 包含未知字段：{', '.join(unknown)}")
    missing = sorted(REQUIRED_KEYS - set(plugin))
    if missing:
        errors.append(f"{prefix} 缺少字段：{', '.join(missing)}")
        return errors

    plugin_id = plugin["pluginId"]
    if not isinstance(plugin_id, str) or not PLUGIN_ID.fullmatch(plugin_id):
        errors.append(f"{prefix}.pluginId 格式无效：{plugin_id!r}")
    elif plugin_id in seen:
        errors.append(f"{prefix}.pluginId 重复：{plugin_id}")
    else:
        seen.add(plugin_id)

    if not isinstance(plugin["name"], str) or not plugin["name"].strip():
        errors.append(f"{prefix}.name 不能为空")

    version = plugin["version"]
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        errors.append(f"{prefix}.version 不是合法语义化版本：{version!r}")

    artifact_type = plugin["artifactType"]
    if artifact_type not in ARTIFACT_TYPES:
        errors.append(f"{prefix}.artifactType 必须是 apk 或 lhplugin：{artifact_type!r}")

    for field in ("sha256", "signerSha256"):
        value = plugin[field]
        if not isinstance(value, str) or not SHA256.fullmatch(value):
            errors.append(f"{prefix}.{field} 必须是 64 位小写十六进制")

    for field in ("url", "repo"):
        value = plugin[field]
        if not isinstance(value, str) or not HTTPS_URL.fullmatch(value):
            errors.append(f"{prefix}.{field} 必须是 https 地址")

    for field in ("minHostVersion", "pluginSdkVersion"):
        if not is_positive_int(plugin[field]):
            errors.append(f"{prefix}.{field} 必须是正整数")

    capabilities = plugin["capabilities"]
    if not isinstance(capabilities, list) or not capabilities:
        errors.append(f"{prefix}.capabilities 必须是非空数组")
    else:
        valid_capabilities = True
        for capability in capabilities:
            if not isinstance(capability, str) or not CAPABILITY.fullmatch(capability):
                errors.append(f"{prefix}.capabilities 含非法能力 ID：{capability!r}")
                valid_capabilities = False
        if valid_capabilities and len(set(capabilities)) != len(capabilities):
            errors.append(f"{prefix}.capabilities 不能重复")

    if "applicationId" in plugin:
        application_id = plugin["applicationId"]
        if not isinstance(application_id, str) or not PLUGIN_ID.fullmatch(application_id):
            errors.append(f"{prefix}.applicationId 格式无效：{application_id!r}")
    if "versionCode" in plugin and not is_positive_int(plugin["versionCode"]):
        errors.append(f"{prefix}.versionCode 必须是正整数")
    if "sizeBytes" in plugin and not is_positive_int(plugin["sizeBytes"]):
        errors.append(f"{prefix}.sizeBytes 必须是正整数")

    if artifact_type == "apk":
        if "applicationId" not in plugin:
            errors.append(f"{prefix}.applicationId 在 APK 条目中必填")
        if "versionCode" not in plugin:
            errors.append(f"{prefix}.versionCode 在 APK 条目中必填")
    elif artifact_type == "lhplugin":
        if "applicationId" in plugin and plugin["applicationId"] != plugin_id:
            errors.append(f"{prefix}.applicationId 必须等于 pluginId")

    return errors


def validate() -> list[str]:
    try:
        raw = REGISTRY.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [f"缺少 {REGISTRY.name}"]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"{REGISTRY.name} 不是合法 JSON：{exc}"]

    if not isinstance(data, dict):
        return [f"{REGISTRY.name} 顶层必须是 JSON 对象"]

    errors: list[str] = []
    unknown = sorted(set(data) - TOP_LEVEL_KEYS)
    if unknown:
        errors.append(f"顶层包含未知字段：{', '.join(unknown)}")

    schema = data.get("schema")
    if not isinstance(schema, int) or isinstance(schema, bool) or schema != 1:
        errors.append("schema 必须为 1")

    if "generatedAt" in data:
        value = data["generatedAt"]
        if not isinstance(value, str):
            errors.append("generatedAt 必须是 ISO-8601 字符串")
        else:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append("generatedAt 必须是 ISO-8601 时间")

    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return errors + ["plugins 必须是数组"]

    seen: set[str] = set()
    for index, plugin in enumerate(plugins):
        errors.extend(validate_plugin(index, plugin, seen))

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print(f"registry.json 校验失败，共 {len(errors)} 个问题：")
        for error in errors:
            print(f"  - {error}")
        return 1

    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    print(f"registry.json 校验通过：schema={data['schema']}, plugins={len(data['plugins'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
