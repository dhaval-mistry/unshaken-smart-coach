param(
    [string]$Project = 'unshaken-smart-coach'
)

# Grafana includes curl, while some pinned store images have no shell or curl.
# Probe over the Compose network; no credentials or exposed store ports are needed.
$checks = [ordered]@{
    'Alloy ready' = 'http://alloy:12345/-/ready'
    'Alloy components' = 'http://alloy:12345/-/healthy'
    'Mimir ready' = 'http://mimir:9009/ready'
    'Loki ready' = 'http://loki:3100/ready'
    'Tempo ready' = 'http://tempo:3200/ready'
    'Grafana ready' = 'http://localhost:3000/api/health'
}

$failed = $false
foreach ($name in $checks.Keys) {
    docker compose -p $Project exec -T grafana curl --noproxy '*' --fail --silent --show-error --output /dev/null $checks[$name]
    if ($LASTEXITCODE -eq 0) {
        Write-Output "$name`: OK"
    } else {
        Write-Output "$name`: unavailable"
        $failed = $true
    }
}
if ($failed) { exit 1 }
Write-Output 'Readiness does not prove that telemetry has been delivered.'
