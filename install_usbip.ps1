# USB/IP 一键安装脚本 (WinJoyCon2-Plus 1.1 附带)
# 内置 usbip-win2 v0.9.7.7 官方 NSIS 安装包，静默安装。
# 必须以管理员身份运行；安装后建议重启。
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$installer = Join-Path $scriptDir 'usbip-win2\v0.9.7.7\USBip-0.9.7.7-x64.exe'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# 0. 提权检查
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "需要管理员权限，正在提权..." -ForegroundColor Yellow
    $argEsc = '"' + $MyInvocation.MyCommand.Path + '"'
    Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',$argEsc -Verb RunAs -Wait
    exit
}

if (-not (Test-Path $installer)) {
    Write-Error "找不到内置安装包：$installer"
    exit 1
}

Write-Step "正在安装 USB/IP v0.9.7.7 ..."
try {
    # NSIS 静默安装 /S，/? 可查看参数；/D= 指定目录（默认 C:\Program Files\USBip）
    $proc = Start-Process -FilePath $installer -ArgumentList '/S' -Wait -PassThru
    Write-Host "安装程序退出码: $($proc.ExitCode)" -ForegroundColor Green
} catch {
    Write-Error "安装失败: $_"
    exit 1
}

Write-Step '验证安装 ...'
$candidates = @(
    "$env:ProgramFiles\USBip\usbip.exe",
    "${env:ProgramFiles(x86)}\USBip\usbip.exe",
    "$env:LOCALAPPDATA\Programs\USBip\usbip.exe",
    "$env:ProgramFiles\usbip-win2\usbip.exe"
)
$found = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($found) {
    Write-Host "USB/IP 已安装: $found" -ForegroundColor Green
    & $found port 2>&1 | ForEach-Object { Write-Host $_ }
} else {
    Write-Host "安装完成但未在常见路径找到 usbip.exe，可能需要重启。" -ForegroundColor Yellow
}

Write-Host ''
Write-Host '完成！强烈建议重启电脑后再使用 WinJoyCon2-Plus。' -ForegroundColor Green
Write-Host '按任意键关闭...'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
