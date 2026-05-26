param(
    [string]$GalleryDlExePath = "",
    [string]$YtDlpExePath = "",
    [switch]$IncludeExternalGalleryDl,
    [switch]$ForceCloseRunningApp
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
$TempDir = Join-Path $RepoRoot ".tmp"
$EntryScript = Join-Path $TempDir "pyinstaller_gui_entry.py"
$AppName = "Instagram to Eagle"
$DistRoot = Join-Path $RepoRoot "dist"
$DistAppDir = Join-Path $DistRoot $AppName
$DistToolsDir = Join-Path $DistAppDir "tools"
$DistAssetsDir = Join-Path $DistAppDir "assets"
$IconPath = Join-Path $RepoRoot "assets\app_icon.ico"
$ExePath = Join-Path $DistAppDir "$AppName.exe"
$MinimumGalleryDlVersion = [version]"1.32.1"

Set-Location $RepoRoot
New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

function Get-RunningPackagedApp {
    $distPrefix = [System.IO.Path]::GetFullPath($DistAppDir)
    return Get-Process -ErrorAction SilentlyContinue | Where-Object {
        try {
            $_.Path -and [System.IO.Path]::GetFullPath($_.Path).StartsWith($distPrefix, [System.StringComparison]::OrdinalIgnoreCase)
        } catch {
            $false
        }
    }
}

function Clear-PreviousBuildOutput {
    if (-not (Test-Path $DistAppDir)) {
        return
    }

    $runningApps = @(Get-RunningPackagedApp)
    if ($runningApps.Count -gt 0) {
        if ($ForceCloseRunningApp) {
            $runningApps | Stop-Process -Force
            Start-Sleep -Milliseconds 500
        } else {
            $processList = ($runningApps | ForEach-Object { "$($_.ProcessName)($($_.Id))" }) -join ", "
            throw "旧版 Instagram to Eagle 仍在运行，无法重新打包。请先关闭程序后重试。正在运行：$processList。也可以运行：.\scripts\build_exe.ps1 -ForceCloseRunningApp"
        }
    }

    $resolvedDistAppDir = [System.IO.Path]::GetFullPath($DistAppDir)
    $resolvedDistRoot = [System.IO.Path]::GetFullPath($DistRoot)
    if (-not $resolvedDistAppDir.StartsWith($resolvedDistRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove unexpected dist path: $resolvedDistAppDir"
    }

    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            Remove-Item -LiteralPath $DistAppDir -Recurse -Force
            return
        } catch {
            if ($attempt -eq 5) {
                throw "无法清理旧发布目录：$DistAppDir。请关闭正在运行的 exe、关闭占用该目录的终端/资源管理器预览/杀毒扫描后重试。原始错误：$($_.Exception.Message)"
            }
            Start-Sleep -Milliseconds (300 * $attempt)
        }
    }
}

Clear-PreviousBuildOutput

@"
import sys

from ins_eagle_sync.config import FROZEN_GALLERY_DL_MODULE_ARG
from ins_eagle_sync.gui import main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == FROZEN_GALLERY_DL_MODULE_ARG:
        import gallery_dl

        del sys.argv[1]
        raise SystemExit(gallery_dl.main())
    main()
"@ | Set-Content -Path $EntryScript -Encoding UTF8

try {
    py -m PyInstaller --version | Out-Null
} catch {
    throw "PyInstaller is not installed. Run: py -m pip install -U pyinstaller"
}

try {
    $galleryDlModuleVersionText = (py -m gallery_dl --version).Trim()
    $galleryDlModuleVersion = [version]$galleryDlModuleVersionText
} catch {
    throw "gallery_dl Python module is not available for bundling. Run: py -m pip install -U gallery-dl"
}

if ($galleryDlModuleVersion -lt $MinimumGalleryDlVersion) {
    throw "gallery_dl Python module is $galleryDlModuleVersionText, but packaging requires $MinimumGalleryDlVersion or newer. Run: py -m pip install -U gallery-dl"
}

Write-Host "Bundling gallery_dl Python module version $galleryDlModuleVersionText"

if (-not (Test-Path $IconPath)) {
    Write-Warning "assets/app_icon.ico was not found. The exe will be built without a custom icon."
}

$pyinstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", $AppName,
    "--distpath", $DistRoot,
    "--paths", "src",
    "--collect-all", "customtkinter",
    "--collect-all", "gallery_dl",
    "--hidden-import", "gallery_dl",
    "--hidden-import", "gallery_dl.__main__",
    "--collect-submodules", "gallery_dl.extractor",
    "--collect-submodules", "gallery_dl.downloader",
    "--collect-submodules", "gallery_dl.postprocessor",
    "--add-data", "README.md;.",
    "--add-data", "config.example.json;."
)

if (Test-Path $IconPath) {
    $pyinstallerArgs += @("--icon", $IconPath)
}

$pyinstallerArgs += $EntryScript
py @pyinstallerArgs

New-Item -ItemType Directory -Force -Path $DistToolsDir | Out-Null
New-Item -ItemType Directory -Force -Path $DistAssetsDir | Out-Null
Copy-Item -Force -Path (Join-Path $RepoRoot "README.md") -Destination (Join-Path $DistAppDir "README.md")
Copy-Item -Force -Path (Join-Path $RepoRoot "config.example.json") -Destination (Join-Path $DistAppDir "config.example.json")
Copy-Item -Force -Path (Join-Path $RepoRoot "assets\*") -Destination $DistAssetsDir -Recurse

function Resolve-ToolSource {
    param(
        [string]$ExplicitPath,
        [string]$RepoRelativePath,
        [string]$CommandName,
        [bool]$AllowPathLookup = $true
    )

    if ($ExplicitPath) {
        return (Resolve-Path $ExplicitPath).Path
    }

    $repoTool = Join-Path $RepoRoot $RepoRelativePath
    if (Test-Path $repoTool) {
        return (Resolve-Path $repoTool).Path
    }

    if ($AllowPathLookup) {
        $pathTool = Get-Command $CommandName -ErrorAction SilentlyContinue
        if ($pathTool) {
            return $pathTool.Source
        }
    }

    return $null
}

$galleryDlSource = $null
if ($GalleryDlExePath) {
    $galleryDlSource = (Resolve-Path $GalleryDlExePath).Path
} elseif ($IncludeExternalGalleryDl) {
    $galleryDlSource = Resolve-ToolSource `
        -ExplicitPath "" `
        -RepoRelativePath "tools\gallery-dl.exe" `
        -CommandName "gallery-dl.exe" `
        -AllowPathLookup $false
}

if ($galleryDlSource) {
    Copy-Item -Force -Path $galleryDlSource -Destination (Join-Path $DistToolsDir "gallery-dl.exe")
    Write-Host "Included tools/gallery-dl.exe from $galleryDlSource"
} else {
    $staleGalleryDl = Join-Path $DistToolsDir "gallery-dl.exe"
    if (Test-Path $staleGalleryDl) {
        Remove-Item -Force -Path $staleGalleryDl
    }
    Write-Warning "Optional: tools/gallery-dl.exe was not included. The packaged app will use bundled gallery_dl Python module version $galleryDlModuleVersionText."
}

$ytDlpSource = Resolve-ToolSource `
    -ExplicitPath $YtDlpExePath `
    -RepoRelativePath "tools\yt-dlp.exe" `
    -CommandName "yt-dlp.exe"

if ($ytDlpSource) {
    Copy-Item -Force -Path $ytDlpSource -Destination (Join-Path $DistToolsDir "yt-dlp.exe")
    Write-Host "Included tools/yt-dlp.exe from $ytDlpSource"
} else {
    Write-Warning "可选：tools/yt-dlp.exe was not included. Some video downloads may use gallery-dl fallback URLs."
}

Write-Host "Build output: $DistAppDir"
Write-Host "EXE: $ExePath"
