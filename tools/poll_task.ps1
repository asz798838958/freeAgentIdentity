param(
    [Parameter(Mandatory=$true)][string]$TaskId,
    [int]$MaxSeconds = 600,
    [int]$IntervalSec = 4,
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$start = Get-Date
$lastLogIdx = 0
while ($true) {
    $elapsed = ((Get-Date) - $start).TotalSeconds
    if ($elapsed -gt $MaxSeconds) {
        Write-Host "TIMEOUT after $MaxSeconds s" -ForegroundColor Red
        break
    }

    try {
        $r = Invoke-WebRequest -Uri "$BaseUrl/api/tasks/$TaskId" -UseBasicParsing -TimeoutSec 10
        $task = $r.Content | ConvertFrom-Json
    } catch {
        Write-Host "[$([int]$elapsed)s] poll error: $_" -ForegroundColor Yellow
        Start-Sleep -Seconds $IntervalSec
        continue
    }

    Write-Host "[$([int]$elapsed)s] status=$($task.status) progress=$($task.progress)"

    if ($task.status -in @('success','failed','interrupted','cancelled')) {
        Write-Host "===== FINAL =====" -ForegroundColor Cyan
        Write-Host "status: $($task.status)"
        Write-Host "error: $($task.error)"
        Write-Host "result:"
        $task.result | ConvertTo-Json -Depth 6
        break
    }
    Start-Sleep -Seconds $IntervalSec
}
