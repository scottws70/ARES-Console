# Build the Windows installer and portable zip into dist\
#   ARES-Console-<ver>-Windows-Setup.exe   (Inno Setup; per-user install, no admin needed)
#   ARES-Console-<ver>-Windows-Portable.zip (unzip and run "ARES Console.cmd")
# Both include a private copy of Python, so nothing else needs to be installed.
param(
  [string]$PyVersion = "3.13.17",
  [string]$PySha256  = "9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38",
  [string]$Iscc      = ""
)
$ErrorActionPreference = "Stop"
$Root  = (Resolve-Path "$PSScriptRoot\..\..").Path
$Ver   = ([regex]::Match((Get-Content "$Root\ares_console\__init__.py" -Raw), '"([^"]+)"')).Groups[1].Value
$Build = "$Root\build"; $Stage = "$Build\stage"; $Dist = "$Root\dist"
Remove-Item -Recurse -Force $Build -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Stage, $Dist | Out-Null

# --- private Python (official embeddable build), verified by SHA-256
$zip = "$Build\python-$PyVersion-embed-amd64.zip"
Invoke-WebRequest "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip" -OutFile $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $PySha256) { throw "Python download hash mismatch: $hash" }
Expand-Archive $zip "$Stage\python"
$pth = Get-ChildItem "$Stage\python\python*._pth" | Select-Object -First 1
# add the install folder (parent of python\) to the import path so "python -m ares_console" works
Set-Content $pth.FullName -Value @("$($pth.BaseName).zip", ".", "..") -Encoding ascii

# --- the app
Copy-Item -Recurse "$Root\ares_console" "$Stage\ares_console"
Get-ChildItem -Recurse -Directory "$Stage\ares_console" -Filter "__pycache__" | Remove-Item -Recurse -Force
Copy-Item "$Root\packaging\icons\ares-console.ico", "$Root\README.md", "$PSScriptRoot\stop_ares_console.py" $Stage
if (Test-Path "$Root\LICENSE") { Copy-Item "$Root\LICENSE" $Stage }

# --- portable zip
$cmd = "@echo off`r`ntitle ARES Console`r`ncd /d `"%~dp0`"`r`n`"%~dp0python\python.exe`" -m ares_console %*`r`n"
Set-Content "$Stage\ARES Console.cmd" -Value $cmd -NoNewline -Encoding ascii
Compress-Archive -Path "$Stage\*" -DestinationPath "$Dist\ARES-Console-$Ver-Windows-Portable.zip" -Force
Remove-Item "$Stage\ARES Console.cmd"

# --- installer
if (-not $Iscc) {
  $Iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
          Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw "Inno Setup 6 (ISCC.exe) not found. Install it: choco install innosetup" }
& $Iscc "/DAppVersion=$Ver" "/DStage=$Stage" "/O$Dist" "$PSScriptRoot\ares-console.iss"
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }
Get-ChildItem $Dist
