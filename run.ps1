# 开发模式启动
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$py = $env:RIFTSTATS_PY
if (-not $py) {
    $py = "C:\Users\Enoch\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
}
if (-not (Test-Path $py)) {
    Write-Host "找不到 Python：$py" -ForegroundColor Red
    Write-Host "设置环境变量 RIFTSTATS_PY 指向你的 python.exe 再试。" -ForegroundColor Yellow
    exit 1
}

# 依赖目录：项目内 -> D 盘公共位置
$libs = $env:RIFTSTATS_LIBS
if (-not $libs) {
    if (Test-Path (Join-Path $root "libs")) { $libs = Join-Path $root "libs" }
    elseif (Test-Path "D:\GetKun\dev\libs") { $libs = "D:\GetKun\dev\libs" }
}
if (-not $libs) {
    Write-Host "找不到依赖目录（libs）。跑 tools\wheel_fetch.py PySide6 装一下。" -ForegroundColor Red
    exit 1
}
Write-Host "依赖: $libs" -ForegroundColor DarkGray

$env:PYTHONPATH = $libs
Push-Location $root
try {
    & $py launch.py @args
} finally {
    Pop-Location
}
