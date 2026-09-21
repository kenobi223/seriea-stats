# Sync rapido per PC secondario - Serie A Stats
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
Set-Location "C:\Users\okrim\Documents\seriea-stats"
Write-Host "=== PULL da GitHub ===" -ForegroundColor Cyan
git pull --ff-only
if ($LASTEXITCODE -eq 0) { Write-Host "Aggiornato all'ultima versione del primo PC" -ForegroundColor Green } else { Write-Host "Conflitto - fai git status" -ForegroundColor Red }
Write-Host "`nPronto per OpenCode - apri opencode in questa cartella" -ForegroundColor Yellow
Write-Host "Per rientrare in chat copia il contenuto di RIENTRA_IN_CHAT.md" -ForegroundColor Gray
pause
