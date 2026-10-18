# Integration smoke test (PowerShell 5.1 / 7): slice one STL for each printer via the gateway.
# Usage: scripts/smoke.ps1 [-Stl <path>] [-OutDir <dir>] [-Base http://localhost:8080]
param(
    [string]$Stl = "D:\OtherProjects\roBa-case\case\v3\freecad\trackball_bearing\generated\print\fit_coupon_print.stl",
    [string]$OutDir = (Join-Path $PSScriptRoot "..\smoke-out"),
    [string]$Base = "http://localhost:8080"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$failed = $false

Write-Host "== health"
Invoke-RestMethod -Uri "$Base/health" | ConvertTo-Json -Compress | Write-Host

foreach ($printer in @("ad4", "ad5mpro")) {
    Write-Host "== $printer : submit $(Split-Path $Stl -Leaf)"
    # curl.exe (bundled with Windows 10+) handles multipart uploads reliably.
    $resp = & curl.exe -fsS -F "file=@$Stl" -F "printer=$printer" "$Base/jobs" | ConvertFrom-Json
    $jobId = $resp.job_id
    Write-Host "job_id=$jobId"

    do {
        Start-Sleep -Seconds 2
        $job = Invoke-RestMethod -Uri "$Base/jobs/$jobId"
    } while ($job.status -eq "queued" -or $job.status -eq "running")

    $job | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 (Join-Path $OutDir "$printer.job.json")
    Write-Host "status=$($job.status)"

    if ($job.status -ne "succeeded") {
        Write-Host "error: $($job.error)"
        $failed = $true
        continue
    }
    Write-Host "validation.passed=$($job.validation.passed)"
    if (-not $job.validation.passed) { $failed = $true }

    foreach ($f in $job.files) {
        $dest = Join-Path $OutDir "$printer-$($f.name)"
        Invoke-WebRequest -Uri "$Base$($f.url)" -OutFile $dest -UseBasicParsing
        $got = (Get-FileHash -Algorithm SHA256 $dest).Hash.ToLower()
        if ($got -eq $f.sha256) {
            Write-Host "downloaded $($f.name) sha256 OK"
        } else {
            Write-Host "sha256 MISMATCH $($f.name)"
            $failed = $true
        }
    }
}

if ($failed) {
    Write-Host "SMOKE FAILED"
    exit 1
}
Write-Host "SMOKE PASSED (outputs in $OutDir)"
