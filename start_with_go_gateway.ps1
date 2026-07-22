param(
    [int]$BackendPort = 8000,
    [int]$GatewayPort = 8787,
    [int]$GatewayAttempts = 4,
    [int]$GatewayTimeoutSeconds = 30,
    [int]$GatewayRaceParallel = 3,
    [int]$GatewayProxyRotations = 6,
    [string]$GatewayDir = "gopay-auto-protocol\20260609\gpt-pp-main",
    [string]$GoExe = "go",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$GatewayPath = Join-Path $Root $GatewayDir
$GatewayUrl = "http://127.0.0.1:$GatewayPort"
$BackendUrl = "http://127.0.0.1:$BackendPort"
$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonExe = "python"
}

function Test-TcpPort {
    param(
        [string]$HostName,
        [int]$Port
    )
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(500)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-TcpPort {
    param(
        [string]$HostName,
        [int]$Port,
        [int]$TimeoutSeconds = 25
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpPort -HostName $HostName -Port $Port) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Show-LogTail {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Write-Host ""
        Write-Host "---- $Path ----"
        Get-Content -LiteralPath $Path -Tail 40
        Write-Host "----------------"
    }
}

Write-Host "Root:        $Root"
Write-Host "Go gateway:  $GatewayUrl"
Write-Host "Backend:     $BackendUrl"
Write-Host ""

if (-not (Test-Path -LiteralPath $GatewayPath)) {
    throw "Go gateway directory not found: $GatewayPath"
}

$env:PAYPAL_PROTOCOL_GATEWAY_URL = $GatewayUrl
$env:PYTHONUTF8 = "1"

if ($DryRun) {
    Write-Host "[dry-run] PAYPAL_PROTOCOL_GATEWAY_URL=$env:PAYPAL_PROTOCOL_GATEWAY_URL"
    Write-Host "[dry-run] Start Go: $GoExe run .\cmd\ppgateway -addr 127.0.0.1:$GatewayPort -attempts $GatewayAttempts -timeout ${GatewayTimeoutSeconds}s -race-parallel $GatewayRaceParallel -proxy-rotations $GatewayProxyRotations"
    Write-Host "[dry-run] Start backend: $PythonExe -m uvicorn main:app --host 0.0.0.0 --port $BackendPort"
    exit 0
}

$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$GatewayOut = Join-Path $LogDir "ppgateway.out.log"
$GatewayErr = Join-Path $LogDir "ppgateway.err.log"

$startedGateway = $false
$gatewayProcess = $null

try {
    if (Test-TcpPort -HostName "127.0.0.1" -Port $GatewayPort) {
        Write-Host "[go] Gateway already listening on $GatewayUrl"
    } else {
        $goCmd = Get-Command $GoExe -ErrorAction SilentlyContinue
        if (-not $goCmd) {
            throw "Go runtime not found: $GoExe. Install Go, add go.exe to PATH, or pass -GoExe C:\Go\bin\go.exe."
        }

        Write-Host "[go] Starting gateway..."
        $gatewayProcess = Start-Process `
            -FilePath $GoExe `
            -ArgumentList @(
                "run", ".\cmd\ppgateway",
                "-addr", "127.0.0.1:$GatewayPort",
                "-attempts", "$GatewayAttempts",
                "-timeout", "${GatewayTimeoutSeconds}s",
                "-race-parallel", "$GatewayRaceParallel",
                "-proxy-rotations", "$GatewayProxyRotations"
            ) `
            -WorkingDirectory $GatewayPath `
            -RedirectStandardOutput $GatewayOut `
            -RedirectStandardError $GatewayErr `
            -WindowStyle Hidden `
            -PassThru
        $startedGateway = $true

        if (-not (Wait-TcpPort -HostName "127.0.0.1" -Port $GatewayPort -TimeoutSeconds 30)) {
            Show-LogTail -Path $GatewayOut
            Show-LogTail -Path $GatewayErr
            throw "Go gateway did not become ready on $GatewayUrl"
        }
        Write-Host "[go] Gateway ready: $GatewayUrl"
    }

    Write-Host "[env] PAYPAL_PROTOCOL_GATEWAY_URL=$env:PAYPAL_PROTOCOL_GATEWAY_URL"
    Write-Host "[backend] Starting main app on $BackendUrl"
    Write-Host "[backend] Press Ctrl+C to stop. If this script started Go gateway, it will be stopped on exit."
    Write-Host ""

    Set-Location -LiteralPath $Root
    & $PythonExe -m uvicorn main:app --host 0.0.0.0 --port $BackendPort
} finally {
    if ($startedGateway -and $gatewayProcess -and -not $gatewayProcess.HasExited) {
        Write-Host ""
        Write-Host "[go] Stopping gateway process $($gatewayProcess.Id)"
        Stop-Process -Id $gatewayProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
