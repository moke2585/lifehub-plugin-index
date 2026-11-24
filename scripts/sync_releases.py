#!/usr/bin/env python3
"""扫描插件仓库的最新 Release，复核产物并更新 registry.json。

由 GitHub Actions 运行；需要 GITHUB_TOKEN，可选 PLUGIN_REPOS（逗号分隔）。
APK 复核依赖 PATH 中的 `apksigner` 与 `aapt2`。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "registry.json"
DEFAULT_REPOS = "moke2585/lifehub-plugin-memo"
ASSET_METADATA = "plugin-release.json"
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
ENTRY_KEYS = {
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
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PACKAGE_LINE = re.compile(
    r"package: name='(?P<name>[^']+)' versionCode='(?P<code>\d+)' versionName='(?P<version>[^']+)'",
)
CERT_DIGEST = re.compile(r"Signer #1 certificate SHA-256 digest: (?P<digest>[0-9a-f]{64})")


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("缺少 GITHUB_TOKEN", file=sys.stderr)
        return 1

    repos = [
        repo.strip()
        for repo in os.environ.get("PLUGIN_REPOS", DEFAULT_REPOS).split(",")
        if repo.strip()
    ]
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entries = {entry["pluginId"]: entry for entry in registry.get("plugins", [])}
    changed = False

    for repo in repos:
        print(f"扫描 {repo}")
        try:
            release = api_json(f"https://api.github.com/repos/{repo}/releases/latest", token)
        except RuntimeError as error:
            if "HTTP 404" in str(error):
                print(f"{repo} 暂无 Release，跳过")
                continue
            raise
        tag = release.get("tag_name") or "latest"
        assets = {asset["name"]: asset for asset in release.get("assets", [])}
        metadata_asset = assets.get(ASSET_METADATA)
        if metadata_asset is None:
            raise RuntimeError(f"{repo} 的最新 Release 缺少 {ASSET_METADATA}")
        metadata = json.loads(download_bytes(metadata_asset["url"], token).decode("utf-8"))
        if metadata.get("schema") != 1 or metadata.get("artifactType") != "apk":
            raise RuntimeError(f"{repo} 的元数据不是 APK schema 1")

        apk_assets = [asset for name, asset in assets.items() if name.endswith(".apk")]
        if len(apk_assets) != 1:
            raise RuntimeError(f"{repo} 的 Release 应包含且只包含一个 APK")
        apk_asset = apk_assets[0]
        if metadata.get("url") != apk_asset["browser_download_url"]:
            raise RuntimeError(f"{repo} 元数据中的 URL 与 Release 资产不一致")

        with tempfile.TemporaryDirectory() as directory:
            apk_path = Path(directory) / apk_asset["name"]
            apk_path.write_bytes(download_bytes(apk_asset["url"], token))
            actual_sha = sha256_file(apk_path)
            if actual_sha != metadata.get("sha256"):
                raise RuntimeError(f"{repo} 的 APK SHA-256 与元数据不一致")
            actual_size = apk_path.stat().st_size
            verify_apk(apk_path, metadata)

        plugin_id = metadata["pluginId"]
        existing = entries.get(plugin_id)
        if existing is not None:
            if existing["signerSha256"] != metadata["signerSha256"]:
                raise RuntimeError(
                    f"{plugin_id} 的签名者发生变化，需要人工审核后再更新索引",
                )
            if existing.get("versionCode", 0) > metadata["versionCode"]:
                raise RuntimeError(f"{plugin_id} 的 versionCode 发生降级")

        entry = {key: metadata[key] for key in ENTRY_KEYS if key in metadata}
        entry["sizeBytes"] = actual_size
        if not SHA256.fullmatch(entry["sha256"]):
            raise RuntimeError(f"{plugin_id} 的 sha256 格式无效")
        if entries.get(plugin_id) != entry:
            entries[plugin_id] = entry
            changed = True
            print(f"更新 {plugin_id} -> {entry['version']} ({tag})")

    if not changed:
        print("registry.json 无变化")
        return 0

    registry["plugins"] = [entries[key] for key in sorted(entries)]
    registry["generatedAt"] = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    REGISTRY.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"registry.json 已更新，共 {len(entries)} 个插件")
    return 0


def api_json(url: str, token: str) -> dict:
    return json.loads(download_bytes(url, token).decode("utf-8"))


def download_bytes(url: str, token: str) -> bytes:
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json, application/octet-stream",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "lifehub-index-bot",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
            if len(data) > MAX_DOWNLOAD_BYTES:
                raise RuntimeError(f"下载内容超过 {MAX_DOWNLOAD_BYTES // 1024 // 1024} MB 上限")
            return data
    except HTTPError as error:
        raise RuntimeError(f"请求失败：{url} -> HTTP {error.code}") from error
    except URLError as error:
        raise RuntimeError(f"请求失败：{url} -> {error.reason}") from error


def verify_apk(path: Path, metadata: dict) -> None:
    apksigner = which("apksigner")
    aapt2 = which("aapt2")
    if apksigner is None or aapt2 is None:
        raise RuntimeError("PATH 中缺少 apksigner 或 aapt2，无法复核 APK")

    cert_output = run([apksigner, "verify", "--print-certs", str(path)])
    cert_match = CERT_DIGEST.search(cert_output)
    if cert_match is None:
        raise RuntimeError("无法从 apksigner 输出读取证书指纹")
    if cert_match.group("digest") != metadata["signerSha256"]:
        raise RuntimeError("APK 证书指纹与元数据不一致")

    badging = run([aapt2, "dump", "badging", str(path)])
    package_match = PACKAGE_LINE.search(badging)
    if package_match is None:
        raise RuntimeError("无法从 aapt2 输出读取包信息")
    if package_match.group("name") != metadata["applicationId"]:
        raise RuntimeError("APK 包名与元数据不一致")
    if int(package_match.group("code")) != metadata["versionCode"]:
        raise RuntimeError("APK versionCode 与元数据不一致")
    if package_match.group("version") != metadata["version"]:
        raise RuntimeError("APK versionName 与元数据不一致")


def which(name: str) -> str | None:
    from shutil import which as find

    return find(name)


def run(command: list[str]) -> str:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"命令失败：{' '.join(command)}\n{result.stderr}")
    return result.stdout + result.stderr


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
