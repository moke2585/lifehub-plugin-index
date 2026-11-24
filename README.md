# LifeHub 插件索引

[LifeHub](https://github.com/moke2585/lifehub) 的静态插件索引。宿主插件市场从这里获取可安装的 `.lhplugin` 与 APK 版本、下载地址、SHA-256、签名者指纹与能力声明。

索引只用于“发现与元数据”，不作为信任根：宿主下载后仍会校验包结构、SHA-256、签名者连续性、版本不降级与能力声明。索引本身由 `registry.sig` 签名，App 内置公钥验签。

## 仓库结构

```text
lifehub-plugin-index/
├── registry.json                     # 索引本体
├── registry.sig                      # 索引签名（ECDSA P-256）
├── keys/index-2026-11.pem            # 索引公钥（App 内置同一份）
├── scripts/validate.py               # 结构与字段校验
├── scripts/sync_releases.py          # 扫描插件 Release，生成索引变更
├── scripts/IndexSignatureTool.java   # 密钥生成、签名与验签（JDK 17）
├── .github/workflows/validate.yml
├── .github/workflows/scan.yml
├── .github/workflows/sign.yml
└── .github/registry-pr-body.md
```

`registry.json` 当前为空索引，并由 `registry.sig` 签名：

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
  "generatedAt": "2026-11-24T00:00:00Z",
  "plugins": [
    {
      "pluginId": "com.lifehub.plugin.memo",
      "name": "任务清单",
      "version": "1.1.0",
      "artifactType": "apk",
      "applicationId": "com.lifehub.plugin.memo",
      "versionCode": 1,
      "url": "https://github.com/moke2585/lifehub-plugin-memo/releases/download/v1.1.0/memo-apk-release.apk",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "signerSha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
      "minHostVersion": 1,
      "pluginSdkVersion": 1,
      "capabilities": ["ui.action", "storage.private"],
      "repo": "https://github.com/moke2585/lifehub-plugin-memo",
      "sizeBytes": 970273
    }
  ]
}
```

顶层字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema` | 整数 | 是 | 固定为 `1` |
| `generatedAt` | 字符串 | 否 | ISO-8601 UTC 生成时间 |
| `plugins` | 数组 | 是 | 每个 `pluginId` 只保留一条最新版本，最多 200 条 |

插件记录字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `pluginId` | 字符串 | 是 | 反向域名，必须与 manifest 一致且全表唯一 |
| `name` | 字符串 | 是 | 展示名称 |
| `version` | 字符串 | 是 | 语义化版本，如 `1.1.0` |
| `artifactType` | 字符串 | 是 | `apk` 或 `lhplugin` |
| `applicationId` | 字符串 | APK 必填 | APK 包名；`.lhplugin` 若填写必须等于 `pluginId` |
| `versionCode` | 整数 | APK 必填 | 用于更新与降级判断 |
| `url` | 字符串 | 是 | HTTPS 下载地址（GitHub Release 资产） |
| `sha256` | 字符串 | 是 | 产物 SHA-256，64 位小写十六进制 |
| `signerSha256` | 字符串 | 是 | APK 证书或 `.lhplugin` 签名公钥的 SHA-256 |
| `minHostVersion` | 整数 | 是 | 最低宿主 versionCode |
| `pluginSdkVersion` | 整数 | 是 | 插件 SDK 主版本 |
| `capabilities` | 字符串数组 | 是 | 与 manifest 一致的能力 ID，非空且不重复 |
| `repo` | 字符串 | 是 | 插件源码仓库 HTTPS 地址 |
| `sizeBytes` | 整数 | 否 | 产物大小，字节 |

v1 不接受未知字段；新增字段需要提升 `schema`。

## 索引签名

`registry.sig`：

```json
{
  "schema": 1,
  "algorithm": "ECDSA_P256_SHA256",
  "keyId": "index-2026-11",
  "registrySha256": "20a3354862d6466af98ce7b05f9b599569784f6c0fedc764ff8e015a05b76af8",
  "signature": "MEUCIQ...",
  "signedAt": "2026-11-24T00:00:00Z"
}
```

- 签名载荷：`lifehub-index-v1\n<registry.json 原始字节的 64 位小写 SHA-256>`，UTF-8。
- 算法：ECDSA P-256 + SHA-256；`keyId` 只允许 `[A-Za-z0-9._-]`。
- App 内置 `assets/market/keys/<keyId>.pem`，按 `keyId` 验签；验签失败回退缓存或内置快照。

本地生成密钥与签名（私钥不要提交）：

```bash
java scripts/IndexSignatureTool.java keygen --private /path/index-private.pem --public keys/index-2026-11.pem
java scripts/IndexSignatureTool.java sign --registry registry.json --key /path/index-private.pem --key-id index-2026-11 --out registry.sig
java scripts/IndexSignatureTool.java verify --registry registry.json --signature registry.sig --public keys/index-2026-11.pem
```

## 上架流程

1. 插件仓库打 `v*` 标签。任务清单插件由 `lifehub-plugin-memo` 的 Release 工作流构建签名 APK，并上传 APK、`.sha256` 与 `plugin-release.json`。
2. `scan.yml` 定时或手动运行：读取最新 Release，下载 APK 并复核 SHA-256、包名、versionCode、versionName 与证书指纹，检查签名者连续性，生成 `registry.json` 变更并开 PR。
3. 维护者按 [PR 模板](.github/registry-pr-body.md) 审核：来源、哈希、签名者、能力、版本与隐私/许可证。
4. 合并后 `sign.yml` 在 GitHub Environment `index-signing` 等待审批，通过后签名并提交 `registry.sig`。
5. App 拉取并验签索引；未签名或签名不匹配时继续使用上一份有效缓存。

第三方插件同样走 PR 审核；扫描工作流不会自动合并。

## CI 与 Secrets

- 任务清单仓库：`LIFEHUB_KEYSTORE_BASE64`、`LIFEHUB_RELEASE_STORE_PASSWORD`、`LIFEHUB_RELEASE_KEY_ALIAS`、`LIFEHUB_RELEASE_KEY_PASSWORD`。
- 本仓库 Environment `index-signing`（需配置 required reviewers）：
  - `INDEX_EC_P256_PRIVATE_KEY_B64`：私钥 PEM 的 Base64；
  - `INDEX_KEY_ID`：`index-2026-11`。
- 公钥 `keys/index-2026-11.pem` 必须与 App `app/src/main/assets/market/keys/index-2026-11.pem` 一致。
- 插件仓库为私有时，扫描与 memo 构建需要只读 Token。

## 校验

```bash
python3 scripts/validate.py
java scripts/IndexSignatureTool.java verify --registry registry.json --signature registry.sig --public keys/index-2026-11.pem
```

`validate.yml` 在每次推送到 `main` 和所有 PR 上运行结构校验；签名由 `sign.yml` 单独生成与验证。

## 当前状态

- 索引为空并已签名；任务清单 APK 首次 `v1.1.0` 发布后由扫描工作流生成第一条记录。
- 记账、旅迹依赖 Kotlin action handler，继续以宿主内置声明式插件分发，不进入索引。
