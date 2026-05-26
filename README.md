# ins-eagle-sync

`ins-eagle-sync` 是一个 Windows 优先的 Python 工具，用 `gallery-dl` 下载 Instagram 内容到本地 staging 目录，再读取 metadata JSON，通过 Eagle Local API 导入 Eagle。

项目提供 GUI 和 CLI 两种入口。下载文件只会进入配置的 staging 目录，不会直接写入 Eagle 资源库。

## 功能概览

- GUI 同步页和设置页，适合日常使用。
- 单帖同步：支持 `/p/`、`/reel/`、`/tv/` 链接。
- 作者主页同步：支持不限制数量、最近 N 条、按时间范围同步。
- Instagram URL 自动规范化：自动清理 query 和 fragment。
- 登录方式：`cookies.txt`、实验性浏览器读取、不登录模式。
- 代理模式：自动检测系统代理、手动代理、不使用代理。
- Eagle 文件夹选择器：在 GUI 内选择目标 Eagle 文件夹。
- staging 预览和手动导入。
- 去重：用 `imported_state` 记录 `unique_key -> eagle_item_id`。
- Eagle 删除校验：用 `--verify-eagle` 检查 Eagle item 是否仍存在且仍属于目标文件夹。

## 安装

建议使用 Windows 的 `py` 启动器。

```powershell
py --version
py -m pip install -e .
py -m gallery_dl --version
```

如果 `gallery-dl` 下载部分视频时提示缺少 `yt-dlp` 或 `youtube-dl`，可以安装：

```powershell
py -m pip install yt-dlp
```

启动 Eagle，并确认 Eagle Local API 可用，默认地址：

```text
http://localhost:41595
```

## GUI 使用

启动 GUI：

```powershell
py -m ins_eagle_sync
```

或：

```powershell
ins-eagle-sync-gui
```

GUI 的基本流程：

1. 在“设置”页配置 staging 目录、缓存目录、Eagle API、cookies 和代理。
2. 在“同步”页选择“单个帖子”或“作者主页”。
3. 粘贴 Instagram URL。
4. 选择 Eagle 目标文件夹。
5. 点击同步，日志面板会实时显示 `gallery-dl` 输出、warning、error 和导入结果。

单个帖子模式只显示单帖需要的参数，不会传 `max_posts` 或时间范围。作者主页模式会显示同步范围参数。

## cookies.txt 获取方法

推荐使用 Netscape 格式的 `cookies.txt`。常见方式：

1. 在浏览器中登录 Instagram。
2. 使用能导出 Netscape cookies 的浏览器扩展，例如 `Get cookies.txt LOCALLY`。
3. 只导出 `instagram.com` 的 cookies。
4. 保存到本地，例如：

   ```text
   E:/INS_Eagle_Sync/_cache/instagram-cookies.txt
   ```

5. 在 `config.json` 或 GUI 设置页中填写：

   ```json
   "cookies": {
     "enabled": true,
     "from_browser": "",
     "file": "E:/INS_Eagle_Sync/_cache/instagram-cookies.txt"
   }
   ```

如果看到 Instagram 跳转登录页、403、401，通常是 cookies 失效，需要重新导出。

## 浏览器读取 cookies

GUI 支持从浏览器读取 cookies，但这是实验性功能。

浏览器读取可能受以下因素影响：

- Chrome/Edge 正在运行并锁定 cookies 数据库。
- Windows DPAPI 解密失败。
- 浏览器配置文件路径和当前用户不一致。
- gallery-dl 或 Python 版本对浏览器 cookies 支持不完整。

如果浏览器读取失败，优先改用导出的 Netscape `cookies.txt`。这是最稳定的方式。

## 代理模式

GUI 设置页提供三种代理模式：

- 自动检测系统代理：推荐普通用户使用。程序会读取环境变量和 Windows 系统代理设置。
- 手动设置代理：适合明确知道代理端口的场景，例如 `http://127.0.0.1:10809` 或 `http://127.0.0.1:7890`。如果只填写 HTTP 代理，程序会自动同时用于 HTTPS。
- 不使用代理：适合无需代理的网络环境。程序会尽量清除传给 gallery-dl 子进程的代理环境变量。

配置示例：

```json
"proxy": {
  "mode": "auto",
  "http_proxy": "",
  "https_proxy": "",
  "detected_proxy": ""
}
```

## Eagle 文件夹选择器

GUI 的 Eagle 文件夹选择器会从 Eagle Local API 读取文件夹列表。可以：

- 选择已有 Eagle 文件夹作为导入目标。
- 搜索文件夹名称或路径。
- 展开树状文件夹结构。
- 把选择结果写回同步页。

如果选择器为空，先确认 Eagle 已启动，并且 Eagle Local API 地址正确。

CLI 也支持用文件夹 ID 或路径：

```powershell
py -m ins_eagle_sync.cli sync-post "https://www.instagram.com/p/DYld7hQCT90/" --folder-id "YOUR_EAGLE_FOLDER_ID"
py -m ins_eagle_sync.cli sync-post "https://www.instagram.com/p/DYld7hQCT90/" --folder-path "Instagram/quinn.xyz"
```

`--folder-id` 和 `--folder-path` 只能二选一。

## 作者主页同步范围

作者主页模式支持三种范围：

- 不限制数量：不传 `--range`，会抓取所有 gallery-dl 可访问的内容。
- 最近 N 条：传 `--max-posts N`，内部会给 gallery-dl 传 `--range 1-N`。
- 按时间范围：传 `--date-from` / `--date-to`，内部会生成 gallery-dl 时间过滤参数。

CLI 示例：

```powershell
py -m ins_eagle_sync.cli sync-author "https://www.instagram.com/quinn.xyz/" --folder-id "YOUR_EAGLE_FOLDER_ID" --max-posts 20
py -m ins_eagle_sync.cli sync-author "https://www.instagram.com/quinn.xyz/" --folder-id "YOUR_EAGLE_FOLDER_ID" --max-posts -1
py -m ins_eagle_sync.cli sync-author "https://www.instagram.com/quinn.xyz/" --folder-id "YOUR_EAGLE_FOLDER_ID" --date-from 2026-04-01 --date-to 2026-05-01
```

`max_posts = -1` 表示不限制数量。`max_posts = 0` 或小于 `-1` 会被视为无效配置并友好报错。

GUI 中“按时间范围”使用结束日期和“天 / 周 / 月 / 年”范围计算起止日期；“最多同步帖子数”默认是 `-1`。

## URL 自动规范化

程序会在 GUI、CLI、gallery-dl 命令、Eagle website 字段和 `unique_key` 生成前统一规范化 Instagram URL。

会自动清理 query 和 fragment：

```text
https://www.instagram.com/p/DPCujtjEowk/?img_index=1
-> https://www.instagram.com/p/DPCujtjEowk/
```

支持：

- `https://www.instagram.com/p/<shortcode>/`
- `https://www.instagram.com/reel/<shortcode>/`
- `https://www.instagram.com/tv/<shortcode>/`
- `https://www.instagram.com/<username>/`

这样可以避免同一个帖子因为 `?img_index=1`、分享参数或 fragment 不同而生成不同的 website / unique key。

## gallery-dl warning 和 timeout

GUI 日志会实时显示 `gallery-dl` 的 stdout / stderr。warning 不等于失败，只有 `gallery-dl` exit code 非 0 才会判定下载失败。

常见 warning：

- `[downloader.ytdl][error] Cannot import yt-dlp or youtube-dl`：表示 ytdl fallback 不可用。若最终文件下载成功，可以忽略；需要时安装 `yt-dlp`。
- `[download][info] Trying fallback URL #1`：gallery-dl 正在尝试备用下载地址。
- `[downloader.http][warning] IncompleteRead...`：网络连接中断，gallery-dl 会按自身重试策略继续尝试。
- `Read timed out`、`HTTPSConnectionPool`、`downloader.http warning`：通常是 Instagram CDN、网络或代理导致的下载超时。

遇到 CDN 超时时，GUI 会显示：

```text
Instagram CDN 下载超时，gallery-dl 正在重试，可能与网络或代理有关。
```

如果 60 秒没有新输出，GUI 会提示“下载仍在进行”；120 秒没有输出会提示“可能卡住”。这只是提示，不会直接判定失败。

## CLI 使用

单帖同步：

```powershell
py -m ins_eagle_sync.cli sync-post "https://www.instagram.com/p/DYld7hQCT90/" --folder-id "YOUR_EAGLE_FOLDER_ID"
```

作者同步：

```powershell
py -m ins_eagle_sync.cli sync-author "https://www.instagram.com/quinn.xyz/" --folder-id "YOUR_EAGLE_FOLDER_ID" --max-posts 20
```

dry-run：

```powershell
py -m ins_eagle_sync.cli sync-post "https://www.instagram.com/p/DYld7hQCT90/" --folder-id "YOUR_EAGLE_FOLDER_ID" --dry-run
```

常用参数：

- `--force`：忽略 `imported_state`，强制重新导入。
- `--verify-eagle`：导入前检查 Eagle 中 item 是否仍存在且仍在目标 folder。
- `--ignore-archive`：忽略 `gallery-dl` archive，允许重新下载。
- `--verbose-gallery-dl`：显示更详细的 `gallery-dl` 日志。
- `--show-annotation`：dry-run 时显示 annotation。

## staging 预览和手动导入

只解析 staging 目录，不调用 Eagle API：

```powershell
py -m ins_eagle_sync.cli parse-staging "E:\INS_Eagle_Sync\_staging\unknown\DYld7hQCT90"
```

把 staging 目录导入 Eagle：

```powershell
py -m ins_eagle_sync.cli import-staging "E:\INS_Eagle_Sync\_staging\unknown\DYld7hQCT90" --folder-id "YOUR_EAGLE_FOLDER_ID"
```

## 打包与发布

开发安装后可直接运行：

```powershell
py -m pip install -e .
ins-eagle-sync-gui
```

发布给普通用户时，用户不需要安装 Python、`py` launcher、`gallery-dl` 或 `yt-dlp`。发布包使用 PyInstaller one-folder 模式，用户双击 exe 启动 GUI。

开发者打包命令：

```powershell
py -m pip install -U pyinstaller
.\scripts\build_exe.ps1
```

打包输出在：

```text
dist/Instagram to Eagle/
```

推荐发布包结构：

```text
dist/
└── Instagram to Eagle/
    ├── Instagram to Eagle.exe
    ├── README.md
    ├── config.example.json
    ├── assets/
    │   └── app_icon.ico
    ├── tools/
    │   ├── gallery-dl.exe  # 可选
    │   └── yt-dlp.exe      # 推荐
    └── _internal/
```

默认打包方式会把 `gallery_dl` Python 包收集进主程序。面向无 Python 用户发布时，发布包至少包含：

- `Instagram to Eagle.exe`
- `README.md`
- `config.example.json`

`gallery-dl.exe` 现在是可选依赖。如果希望覆盖内置模块版本，或临时使用指定版本，可以把外置程序放到 `tools/gallery-dl.exe`。`yt-dlp.exe` 是推荐依赖，用于减少部分视频下载时的 `Cannot import yt-dlp or youtube-dl` warning。缺少它不一定导致同步失败，gallery-dl 可能会继续尝试备用下载方式。

打包脚本会复制：

- `README.md`
- `config.example.json`
- `assets/`
- `tools/gallery-dl.exe`，如果存在
- `tools/yt-dlp.exe`，如果存在

打包脚本不会复制：

- `config.json`
- `cookies.txt`
- `_cache/`
- `_staging/`
- `.pytest_cache/`
- `__pycache__/`

默认打包会内置当前 Python 环境中的 `gallery_dl` 包，并要求版本至少为 `1.32.1`。可以显式指定工具 exe：

```powershell
.\scripts\build_exe.ps1 -GalleryDlExePath "C:\path\to\gallery-dl.exe" -YtDlpExePath "C:\path\to\yt-dlp.exe"
```

如果不传参数，脚本不会复制项目根目录的 `tools/gallery-dl.exe`，而是使用 PyInstaller 内置的 `gallery_dl` 模块，避免旧版 exe 覆盖新版模块。只有传入 `-GalleryDlExePath`，或显式使用 `-IncludeExternalGalleryDl` 时，才会复制外置 `gallery-dl.exe`。`yt-dlp.exe` 会优先读取项目根目录的 `tools/yt-dlp.exe`，然后尝试从 PATH 查找。

如果 `gallery-dl.exe` 缺失，脚本会输出可选 warning，发布包会使用内置的 `gallery_dl` Python 模块下载。如果 `yt-dlp.exe` 缺失，脚本会输出可选 warning。

`gallery-dl` 运行时查找策略：

1. 配置中显式设置的 `gallery_dl_executable`
2. 打包环境：`tools/gallery-dl.exe`
3. 打包环境：`gallery-dl.exe`
4. 打包环境 fallback：主程序内置的 `gallery_dl` Python 模块
5. 开发环境：`tools/gallery-dl.exe`
6. 开发环境：`gallery-dl.exe`
7. 开发环境 fallback：`py -m gallery_dl`

打包环境不会 fallback 到用户系统里的 `py -m gallery_dl`，因此普通用户仍然不需要安装 Python 或 gallery-dl。

`yt-dlp` 运行时查找策略：

1. 配置中显式设置的 `yt_dlp_executable`
2. 打包环境：`tools/yt-dlp.exe`
3. 打包环境：`yt-dlp.exe`
4. 开发环境：`tools/yt-dlp.exe`
5. 开发环境：`yt-dlp.exe`
6. 开发环境 fallback：`py -m yt_dlp`

打包环境找不到 `yt-dlp` 时只提示，不会直接判定任务失败。

打包后仍需要准备或确认：

- 可写的 `_cache` 和 `_staging` 目录
- 有效的 `cookies.txt`
- 已启动的 Eagle

`cookies.txt` 不会内置进发布包，用户需要在 GUI 设置页选择。`config.json` 会在用户首次保存设置时生成；设置不会被写进 exe。只要发布或升级时保留 `config.json`，cookies 路径、保存地址、代理和 Eagle 文件夹设置就不会清空。删除 `config.json` 或换到一个没有 `config.json` 的新目录运行时，程序会按默认配置重新创建。

GUI 启动检查会显示当前是开发环境还是已打包运行，并提示 `gallery-dl` / `yt-dlp` 是否可用。如果存在 `tools/gallery-dl.exe`，会显示已找到内置 exe；如果没有 exe 但 PyInstaller 已正确收集模块，会显示已内置 `gallery-dl Python 模块`。

## 应用图标

图标文件位于：

```text
assets/app_icon.ico
```

如果需要从 PNG 重新生成 ico，可以放置 `assets/app_icon.png`，或使用现有 `assets/icon.png`，然后运行：

```powershell
py scripts/make_icon.py
```

生成的 ico 包含 16、24、32、48、64、128、256 多尺寸。PyInstaller 打包时会使用 `assets/app_icon.ico` 作为 exe 图标，GUI 运行时也会用它作为窗口图标。

## 常见问题

### UI 打不开

先在终端运行，查看具体报错：

```powershell
py -m ins_eagle_sync
```

如果提示缺少依赖，重新安装：

```powershell
py -m pip install -e .
```

### cookies 失效

看到登录跳转、401、403 或抓不到内容时，重新导出 Instagram `cookies.txt`，并确认 `cookies.enabled` 为 `true`，`cookies.file` 指向正确路径。

### 浏览器 cookies Permission denied

关闭浏览器后重试。如果仍失败，改用 Netscape `cookies.txt`。

### 代理不生效

确认代理软件正在运行，端口和 GUI 里填写的一致。自动检测不稳定时，改用手动代理。无需代理时选择“不使用代理”。

### gallery-dl 成功但导入 0 个文件

常见原因：

- URL 或作者主页没有可访问内容。
- cookies 失效导致只拿到空结果。
- 时间范围太窄。
- `gallery-dl` archive 已记录旧下载，导致没有新文件。
- staging 目录中没有 metadata JSON。

可以尝试缩小范围、更新 cookies、使用 `--ignore-archive`，或查看 GUI 实时日志。

### Eagle 已删除但仍 skipped

使用 folder-aware 校验：

```powershell
py -m ins_eagle_sync.cli verify-imports --shortcode DYld7hQCT90 --folder-id "YOUR_EAGLE_FOLDER_ID" --dry-run
py -m ins_eagle_sync.cli import-staging "E:\INS_Eagle_Sync\_staging\unknown\DYld7hQCT90" --folder-id "YOUR_EAGLE_FOLDER_ID" --verify-eagle
```

### gallery-dl archive 导致不重新下载

使用 `--ignore-archive`：

```powershell
py -m ins_eagle_sync.cli sync-post "https://www.instagram.com/p/DYld7hQCT90/" --folder-id "YOUR_EAGLE_FOLDER_ID" --ignore-archive
```

## 不要提交这些文件

不要提交包含账号、cookies 或本地运行数据的文件：

- `cookies.txt`
- `config.json`
- `_cache/`
- `_staging/`
- `tools/*.exe`
- `tools/gallery-dl.exe`
- `tools/yt-dlp.exe`
- `eagle-imported.json`
- `gallery-dl-archive.sqlite3`
- `*.spec`

检查工作区：

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
