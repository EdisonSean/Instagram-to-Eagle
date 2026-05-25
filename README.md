# ins-eagle-sync

`ins-eagle-sync` 是一个 Windows 优先的 Python CLI 工具，用 `gallery-dl` 下载 Instagram 内容到本地 staging 目录，再读取 metadata JSON，通过 Eagle Local API 导入 Eagle。

项目只做 CLI，不做 GUI，也不做 Eagle 插件。下载文件不会直接写入 Eagle 资源库。

## 项目用途

这个项目用于把 Instagram 作者主页、单帖或 Reel 中的图片和视频整理进 Eagle：先通过 `gallery-dl` 下载到本地 staging 目录，再根据 `gallery-dl` 生成的 metadata 生成 Eagle 标题、网址、注释和标签，最后通过 Eagle Local API 导入到指定 Eagle 文件夹。

## 功能

- 单帖同步：支持 `https://www.instagram.com/p/<shortcode>/` 和 `https://www.instagram.com/reel/<shortcode>/`
- 作者同步：支持 `https://www.instagram.com/<username>/`
- staging 预览：扫描已下载媒体和 metadata，查看将导入 Eagle 的字段
- 手动导入：把 staging 目录中的媒体导入指定 Eagle 文件夹
- 去重：用 `imported_state` 记录 `unique_key -> eagle_item_id`
- Eagle 删除校验：用 `--verify-eagle` 和 `verify-imports --folder-id` 检查 Eagle item 是否仍存在且仍属于目标文件夹

## 前置准备

1. 安装 Python。

   建议使用 Windows 的 `py` 启动器：

   ```powershell
   py --version
   ```

2. 安装依赖。

   ```powershell
   py -m pip install -e .
   ```

3. 安装或确认 `gallery-dl` 可用。

   项目默认通过 `py -m gallery_dl` 调用 `gallery-dl`。如果按 editable install 安装本项目，`gallery-dl` 会作为依赖安装。

   ```powershell
   py -m gallery_dl --version
   ```

4. 可选安装 `yt-dlp`。

   Instagram 部分视频下载失败时，`gallery-dl` 可能提示缺少 `yt-dlp` 或 `youtube-dl`。可按需安装：

   ```powershell
   py -m pip install yt-dlp
   ```

5. 启动 Eagle。

   Eagle Local API 默认地址是：

   ```text
   http://localhost:41595
   ```

6. 准备 Instagram cookies。

   推荐导出 Netscape 格式的 `cookies.txt`，然后在 `config.json` 里设置：

   ```json
   "cookies": {
     "enabled": true,
     "from_browser": "",
     "file": "E:/INS_Eagle_Sync/_cache/instagram-cookies.txt"
   }
   ```

7. 配置代理模式。

   普通用户建议使用自动检测系统代理。程序会尝试读取环境变量和 Windows 系统代理设置：

   ```json
   "proxy": {
     "mode": "auto",
     "http_proxy": "",
     "https_proxy": "",
     "detected_proxy": ""
   }
   ```

   如果你知道代理端口，也可以切换到手动设置代理，例如 `http://127.0.0.1:10809` 或 `http://127.0.0.1:7890`。无需代理的网络环境可以选择不使用代理。

## 配置

先复制配置示例：

```powershell
Copy-Item config.example.json config.json
```

示例：

```json
{
  "gallery_dl_executable": "py -m gallery_dl",
  "staging_dir": "E:/INS_Eagle_Sync/_staging",
  "archive_db": "E:/INS_Eagle_Sync/_cache/gallery-dl-archive.sqlite3",
  "imported_state": "E:/INS_Eagle_Sync/_cache/eagle-imported.json",
  "eagle_api_base": "http://localhost:41595",
  "default_eagle_root_folder": "Instagram",
  "title_caption_chars": 70,
  "proxy": {
    "mode": "auto",
    "http_proxy": "",
    "https_proxy": "",
    "detected_proxy": ""
  },
  "cookies": {
    "enabled": true,
    "from_browser": "",
    "file": "E:/INS_Eagle_Sync/_cache/instagram-cookies.txt"
  },
  "download": {
    "sleep_request": "8-15",
    "max_posts": -1
  }
}
```

字段说明：

- `gallery_dl_executable`：调用 `gallery-dl` 的命令，默认 `py -m gallery_dl`
- `staging_dir`：下载暂存目录
- `archive_db`：`gallery-dl` archive 数据库，避免重复下载
- `imported_state`：Eagle 导入状态文件，用于避免重复导入
- `eagle_api_base`：Eagle Local API 地址
- `title_caption_chars`：Eagle 标题使用 caption 前多少个可见字符
- `proxy`：代理模式。`auto` 自动检测系统代理，`manual` 使用手动代理，`none` 不使用代理
- `cookies`：Instagram 登录 cookies
- `download.max_posts`：作者同步时最多下载多少条。`50` 表示最多抓取 50 条，`-1` 表示不限制数量

## 单帖同步

一键下载并导入单个帖子：

```powershell
py -m ins_eagle_sync.cli sync-post "https://www.instagram.com/p/DYld7hQCT90/" --folder-id "YOUR_EAGLE_FOLDER_ID"
```

也可以使用 Eagle 文件夹路径，程序会自动创建缺失的文件夹并使用最终 folder id：

```powershell
py -m ins_eagle_sync.cli sync-post "https://www.instagram.com/p/DYld7hQCT90/" --folder-path "Instagram/quinn.xyz"
```

dry-run 预览：

```powershell
py -m ins_eagle_sync.cli sync-post "https://www.instagram.com/p/DYld7hQCT90/" --folder-id "YOUR_EAGLE_FOLDER_ID" --dry-run
```

常用参数：

- `--force`：忽略 imported_state，强制重新导入
- `--verify-eagle`：导入前检查 Eagle 中 item 是否仍存在且仍在目标 folder
- `--ignore-archive`：忽略 `gallery-dl` archive，允许重新下载
- `--verbose-gallery-dl`：显示更详细的 `gallery-dl` 日志
- `--show-annotation`：dry-run 时显示 annotation

## 作者同步

一键同步整个作者：

```powershell
py -m ins_eagle_sync.cli sync-author "https://www.instagram.com/quinn.xyz/" --folder-id "YOUR_EAGLE_FOLDER_ID"
```

使用 Eagle 文件夹路径：

```powershell
py -m ins_eagle_sync.cli sync-author "https://www.instagram.com/quinn.xyz/" --folder-path "Instagram/quinn.xyz"
```

限制最多同步 20 条：

```powershell
py -m ins_eagle_sync.cli sync-author "https://www.instagram.com/quinn.xyz/" --folder-id "YOUR_EAGLE_FOLDER_ID" --max-posts 20
```

不限制同步数量：

```powershell
py -m ins_eagle_sync.cli sync-author "https://www.instagram.com/quinn.xyz/" --folder-id "YOUR_EAGLE_FOLDER_ID" --max-posts -1
```

`-1` 会抓取所有可访问内容，可能耗时较长，也更容易触发平台限制。首次使用建议先用较小数字测试。

带 Eagle 状态校验：

```powershell
py -m ins_eagle_sync.cli sync-author "https://www.instagram.com/quinn.xyz/" --folder-id "YOUR_EAGLE_FOLDER_ID" --verify-eagle
```

## Eagle 文件夹管理

列出 Eagle 文件夹：

```powershell
py -m ins_eagle_sync.cli list-folders
```

输出包含：

- `id`
- `name`
- `parent_id`
- `path`

确保文件夹路径存在，不存在则逐级创建：

```powershell
py -m ins_eagle_sync.cli ensure-folder "Instagram/quinn.xyz"
```

示例路径：

```text
Instagram/quinn.xyz
```

会检查或创建：

```text
Instagram
Instagram/quinn.xyz
```

`sync-post`、`sync-author`、`import-staging`、`verify-imports` 都支持：

- `--folder-id`
- `--folder-path`

两者只能选一个。如果同时传入，CLI 会报错并退出。需要最稳定、最明确的行为时优先使用 `--folder-id`；想减少手动复制 folder id 时使用 `--folder-path`。

## staging 预览

只解析 staging 目录，不调用 Eagle API，不修改文件：

```powershell
py -m ins_eagle_sync.cli parse-staging "E:\INS_Eagle_Sync\_staging\unknown\DYld7hQCT90"
```

输出包括：

- `file_path`
- `title`
- `website`
- `tags`
- `unique_key`

## 手动导入

把 staging 目录导入 Eagle：

```powershell
py -m ins_eagle_sync.cli import-staging "E:\INS_Eagle_Sync\_staging\unknown\DYld7hQCT90" --folder-id "YOUR_EAGLE_FOLDER_ID"
```

使用 Eagle 文件夹路径：

```powershell
py -m ins_eagle_sync.cli import-staging "E:\INS_Eagle_Sync\_staging\unknown\DYld7hQCT90" --folder-path "Instagram/quinn.xyz"
```

dry-run：

```powershell
py -m ins_eagle_sync.cli import-staging "E:\INS_Eagle_Sync\_staging\unknown\DYld7hQCT90" --folder-id "YOUR_EAGLE_FOLDER_ID" --dry-run
```

带 Eagle 状态校验：

```powershell
py -m ins_eagle_sync.cli import-staging "E:\INS_Eagle_Sync\_staging\unknown\DYld7hQCT90" --folder-id "YOUR_EAGLE_FOLDER_ID" --verify-eagle
```

## Eagle 删除后重新导入

如果你在 Eagle 中删除了素材，普通导入可能仍会因为 `imported_state` 中存在记录而跳过。此时有三种处理方式。

### 1. 导入时校验 Eagle

```powershell
py -m ins_eagle_sync.cli import-staging "E:\INS_Eagle_Sync\_staging\unknown\DYld7hQCT90" --folder-id "YOUR_EAGLE_FOLDER_ID" --verify-eagle
```

`--verify-eagle` 会检查：

- item 是否仍存在
- item 是否 `isDeleted`
- item 是否仍属于传入的 `--folder-id`

如果 item 已删除或不在目标 folder，会删除对应 imported_state 记录并允许重新导入。

### 2. 批量校验 imported_state

dry-run：

```powershell
py -m ins_eagle_sync.cli verify-imports --shortcode DYld7hQCT90 --folder-id "YOUR_EAGLE_FOLDER_ID" --dry-run
```

也可以使用 Eagle 文件夹路径，程序会先解析为 folder id 再做 folder-aware 校验：

```powershell
py -m ins_eagle_sync.cli verify-imports --shortcode DYld7hQCT90 --folder-path "Instagram/quinn.xyz" --dry-run
```

实际删除 stale state：

```powershell
py -m ins_eagle_sync.cli verify-imports --shortcode DYld7hQCT90 --folder-id "YOUR_EAGLE_FOLDER_ID"
```

输出分类：

- `alive`：item 存在且在目标 folder 内
- `missing`：item 不存在、已删除或 Eagle 返回 `File does not exist`
- `alive_but_not_in_folder`：item 仍在 Eagle 库中，但不在目标 folder 内
- `unknown`：Eagle 未启动、网络失败、超时、无法解析响应等

### 3. 手动忘记导入记录

按 shortcode 删除：

```powershell
py -m ins_eagle_sync.cli forget-import --shortcode DYld7hQCT90
```

按 username + shortcode 删除：

```powershell
py -m ins_eagle_sync.cli forget-import --username quinn.xyz --shortcode DYld7hQCT90
```

按 unique_key 删除：

```powershell
py -m ins_eagle_sync.cli forget-import --unique-key instagram:quinn.xyz:DYld7hQCT90:01
```

dry-run：

```powershell
py -m ins_eagle_sync.cli forget-import --shortcode DYld7hQCT90 --dry-run
```

非 dry-run 会先备份：

```text
eagle-imported.json.bak
```

## 常见问题

### gallery-dl archive 导致不重新下载

`gallery-dl` 会用 `archive_db` 记录已经下载过的项目。如果你想重新下载，用：

```powershell
py -m ins_eagle_sync.cli sync-post "https://www.instagram.com/p/DYld7hQCT90/" --folder-id "YOUR_EAGLE_FOLDER_ID" --ignore-archive
```

作者同步同理：

```powershell
py -m ins_eagle_sync.cli sync-author "https://www.instagram.com/quinn.xyz/" --folder-id "YOUR_EAGLE_FOLDER_ID" --ignore-archive
```

### Eagle 已删除但仍 skipped

优先使用 folder-aware 校验：

```powershell
py -m ins_eagle_sync.cli verify-imports --shortcode DYld7hQCT90 --folder-id "YOUR_EAGLE_FOLDER_ID" --dry-run
py -m ins_eagle_sync.cli verify-imports --shortcode DYld7hQCT90 --folder-path "Instagram/quinn.xyz" --dry-run
py -m ins_eagle_sync.cli import-staging "E:\INS_Eagle_Sync\_staging\unknown\DYld7hQCT90" --folder-id "YOUR_EAGLE_FOLDER_ID" --verify-eagle
```

如果 imported_state 是旧记录且没有 `eagle_item_id`，程序只会在严格匹配到 Eagle item 时自动回填。匹配条件包含 folder、website、Shortcode 和媒体序号，避免把 01 误匹配到 02/03。

### cookies 失效

如果看到 Instagram 跳转登录页：

```text
HTTP redirect to login page
```

重新导出 Instagram `cookies.txt`，并确认 `config.json` 中 `cookies.enabled` 为 `true`，`cookies.file` 指向正确路径。

### Chrome cookies Permission denied

如果用 `cookies.from_browser` 遇到 Chrome cookies 权限或 DPAPI 解密问题，改用导出的 Netscape `cookies.txt`：

```json
"cookies": {
  "enabled": true,
  "from_browser": "",
  "file": "E:/INS_Eagle_Sync/_cache/instagram-cookies.txt"
}
```

### 代理不生效

GUI 设置页提供三种代理模式：

- 自动检测系统代理：推荐给普通用户，会尝试读取系统代理或环境变量。
- 手动设置代理：适合知道代理端口的用户，例如 `http://127.0.0.1:10809` 或 `http://127.0.0.1:7890`。如果只填写 HTTP 代理，程序会自动同时用于 HTTPS。
- 不使用代理：适合无需代理的网络环境，程序会尽量清除传给子进程的代理环境变量。

如果下载失败，可以尝试：

- 检查代理软件是否开启。
- 切换到手动设置代理，并确认端口和代理软件一致。
- 清空代理或选择不使用代理后重试。
- 检查 cookies 是否有效。

## 不要提交这些文件

不要提交包含账号、cookies 或本地运行数据的文件：

- `cookies.txt`
- `config.json`
- `_cache/`
- `_staging/`
- `eagle-imported.json`
- `gallery-dl-archive.sqlite3`

这些已经应该由 `.gitignore` 忽略。提交前可检查：

```powershell
git status --short
```

## 开发

运行测试：

```powershell
py -m pytest -q
```

或：

```powershell
.\scripts\run_dev.ps1
```
