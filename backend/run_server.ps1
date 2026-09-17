# 서버 실행 스크립트
# 사용법: PowerShell에서 backend 폴더 기준으로 실행
#   .\run_server.ps1

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$dbPath = Join-Path $PSScriptRoot "game.db"
$appDir = Join-Path $PSScriptRoot "app"

if (-not (Test-Path $dbPath)) {
    Write-Host "게임 DB가 없어서 처음 한 번 초기화합니다..."
    Push-Location $appDir
    & $venvPython seed_data.py
    Pop-Location
}

Write-Host "서버를 시작합니다. 같은 공유기의 다른 사람도 접속할 수 있게 0.0.0.0으로 엽니다."
Push-Location $appDir
& $venvPython -m uvicorn main:app --host 0.0.0.0 --port 8123
Pop-Location
