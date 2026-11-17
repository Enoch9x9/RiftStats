# 打便携版：onedir 形式，解压即用，不需要运行时解包
param(
    [string]$Name = "RiftStats"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$py = $env:RIFTSTATS_PY
if (-not $py) { $py = "C:\Users\Enoch\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" }

# 依赖目录：项目内 -> D 盘公共位置
$libs = $env:RIFTSTATS_LIBS
if (-not $libs) {
    if (Test-Path (Join-Path $root "libs")) { $libs = Join-Path $root "libs" }
    elseif (Test-Path "D:\GetKun\dev\libs") { $libs = "D:\GetKun\dev\libs" }
}
if (-not $libs) { Write-Host "找不到 libs 目录" -ForegroundColor Red; exit 1 }
Write-Host "依赖: $libs" -ForegroundColor DarkGray
$env:PYTHONPATH = $libs
$env:TEMP = Join-Path $root ".tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null

# 构建产物全部放 D 盘，不占 C
$devDir = "D:\GetKun\dev"
New-Item -ItemType Directory -Force -Path $devDir | Out-Null
$workPath = Join-Path $devDir "build"
$distPath = Join-Path $devDir "dist"
$specPath = Join-Path $devDir "spec"

Write-Host "== 清理旧产物 ==" -ForegroundColor Cyan
Remove-Item -Recurse -Force $workPath, $distPath -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path $specPath "$Name.spec") -ErrorAction SilentlyContinue

Write-Host "== 打包 onedir ==" -ForegroundColor Cyan
& $py -m PyInstaller `
    --noconfirm --clean --onedir --console `
    --name $Name `
    --workpath "$workPath" `
    --distpath "$distPath" `
    --specpath "$specPath" `
    --icon "$root\assets\riftstats.ico" `
    --add-data "$root\assets;assets" `
    --paths "$libs" `
    --paths "$root" `
    --exclude-module tkinter `
    --exclude-module PySide6.QtWebEngineCore `
    --exclude-module PySide6.Qt3DCore `
    --exclude-module PySide6.QtQuick3D `
    launch.py

if ($LASTEXITCODE -ne 0) { Write-Host "打包失败" -ForegroundColor Red; exit $LASTEXITCODE }

$out = Join-Path $distPath $Name
Copy-Item "README.md" "$out\README.md" -ErrorAction SilentlyContinue

$size = [math]::Round(((Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum)/1MB, 1)
Write-Host "== 完成：$out （$size MB）==" -ForegroundColor Green
Get-ChildItem $out | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } } | Format-Table
