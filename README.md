# LifeHub 插件索引

[LifeHub](https://github.com/moke2585/lifehub) 的静态插件索引（阶段 E）。宿主插件市场从这里获取可安装的 `.lhplugin` 与 APK 版本、下载地址、SHA-256、签名者指纹与能力声明。

索引只用于“发现与元数据”，不作为信任根：宿主下载后仍会校验包结构、SHA-256、签名者连续性、版本不降级与能力声明。

## 仓库结构

```text
lifehub-plugin-index/
├── registry.json               # 索引本体
├── scripts/validate.py         # 结构与字段校验（仅标准库）
└── .github/workflows/validate.yml
```

`registry.json` 当前为空索引：

```json
{
  "schema": 1,
  "plugins": []
}
```

## 索引结构（schema v1）

```json
{
  "schema": 1,
  "generatedAt": "2026-11-23T00:00:00Z",
  "plugins": [
    {
      "pluginId": "com.lifehub.plugin.memo",
      "name": "任务清单",
      "version": "1.1.0",
      "artifactType": "apk",
      "url": "https://github.com/moke2585/lifehub-plugin-memo/releases/download/v1.1.0/memo-apk-release.apk",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "signerSha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
      "minHostVersion": 1,
      "pluginSdkVersion": 1,
      "capabilities": ["ui.action", "storage.private"],
      "repo": "https://github.com/moke2585/lifehub-plugin-memo"
    }
  ]
}
```

顶层字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema` | 整数 | 是 | 固定为 `1` |
| `generatedAt` | 字符串 | 否 | ISO-8601 生成时间，便于缓存与审计 |
| `plugins` | 数组 | 是 | 插件记录，每个 `pluginId` 只保留一条最新版本 |

插件记录字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `pluginId` | 字符串 | 是 | 反向域名格式，必须与 manifest 一致且全表唯一 |
| `name` | 字符串 | 是 | 展示名称 |
| `version` | 字符串 | 是 | 语义化版本，如 `1.1.0` |
| `artifactType` | 字符串 | 是 | `apk` 或 `lhplugin` |
| `url` | 字符串 | 是 | HTTPS 下载地址（GitHub Release 资产） |
| `sha256` | 字符串 | 是 | 产物 SHA-256，64 位小写十六进制 |
| `signerSha256` | 字符串 | 是 | APK 证书或 `.lhplugin` 签名公钥的 SHA-256 |
| `minHostVersion` | 整数 | 是 | 最低宿主 versionCode |
| `pluginSdkVersion` | 整数 | 是 | 插件 SDK 主版本，当前为 `1` |
| `capabilities` | 字符串数组 | 是 | 与 manifest 一致的能力 ID，非空且不重复 |
| `repo` | 字符串 | 是 | 插件源码仓库 HTTPS 地址 |

v1 不接受未知字段；新增字段需要提升 `schema`。

## 发布新版本

1. 在插件仓库打版本标签，CI 构建并签名产物（`.lhplugin` 或 APK），上传到 GitHub Release。
2. 计算产物哈希与签名者指纹：

```bash
sha256sum memo-apk-release.apk
apksigner verify --print-certs memo-apk-release.apk
```

3. 在 `registry.json` 中新增或替换该 `pluginId` 的记录（只保留最新版本）。
4. 本地校验后提交：

```bash
python3 scripts/validate.py
```

5. 合并到 `main` 后，宿主按 ETag 拉取新索引；已安装插件始终本地发现，索引损坏或断网不影响运行。

## 校验

```bash
python3 scripts/validate.py
```

CI 在每次推送到 `main` 和所有 Pull Request 上运行同一脚本，检查 JSON 结构、必填字段、唯一性、版本格式、哈希格式、HTTPS 地址与能力 ID。

## 当前状态

- 记账、旅迹仍以宿主内置声明式插件分发，暂不进入索引。
- 任务清单将作为 APK 插件发布；Release 资产与记录在首次发布后补充。
