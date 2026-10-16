# solidcraft/*/*.json を全て生成物(STEP/STL/3MF/PNG/eval JSON)に変換する。
$ErrorActionPreference = 'Stop'
$cli = Join-Path $env:LOCALAPPDATA 'Programs\SolidCraft\solidcraft-0.13.1-windows-x64-portable\solidcraft-cli.exe'
if (-not (Test-Path $cli)) { throw "solidcraft-cli not found: $cli" }
foreach ($script in Get-ChildItem -Path $PSScriptRoot -Directory | ForEach-Object { Get-ChildItem -Path $_.FullName -Filter *.json -File }) {
    $name = $script.BaseName
    $gen = Join-Path $script.DirectoryName 'generated'
    New-Item -ItemType Directory -Force $gen | Out-Null
    $in = $script.FullName
    & $cli run $in --out (Join-Path $gen "$name.step") --out (Join-Path $gen "$name.stl") --out (Join-Path $gen "$name.3mf") --quiet
    if ($LASTEXITCODE -ne 0) { throw "run failed: $in" }
    & $cli eval $in --json-out (Join-Path $gen "$name.eval.json")
    if ($LASTEXITCODE -ne 0) { throw "eval failed: $in" }
    & $cli snapshot $in --out (Join-Path $gen "$name.iso.png") --view iso --width 1200 --height 900
    if ($LASTEXITCODE -ne 0) { throw "snapshot failed: $in" }
    Write-Host "built $name -> $gen"
}
