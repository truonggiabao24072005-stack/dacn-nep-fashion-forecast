$ErrorActionPreference='Stop'
$fashionRoot=$PSScriptRoot
$fashionPython=Join-Path $fashionRoot '.venv\Scripts\python.exe'
if(-not(Test-Path -LiteralPath $fashionPython)){throw 'Chưa có môi trường Python. Xem README.md để cài đặt.'}
$fashionPgBin='C:\Program Files\PostgreSQL\18\bin'
$fashionPgData=Join-Path $fashionRoot '.runtime\pgdata'
if(Test-Path -LiteralPath $fashionPgData){
 & "$fashionPgBin\pg_ctl.exe" -D $fashionPgData status 2>$null | Out-Null
 if($LASTEXITCODE -ne 0){& "$fashionPgBin\pg_ctl.exe" -D $fashionPgData -l (Join-Path $fashionRoot '.runtime\postgres.log') -o '-h 127.0.0.1 -p 55438 -c max_connections=50 -c shared_buffers=64MB' -w start}
 if($LASTEXITCODE -ne 0){throw 'Không khởi động được PostgreSQL. Xem .runtime\postgres.log.'}
}
Set-Location -LiteralPath $fashionRoot
& $fashionPython manage.py check
if($LASTEXITCODE -ne 0){throw 'Cấu hình chưa hợp lệ. Xem thông báo kiểm tra ở trên.'}
& $fashionPython tools/start_server.py
if($LASTEXITCODE -ne 0){throw 'Không mở được website. Xem .runtime\web.log.'}
Write-Host 'Website đã sẵn sàng: http://127.0.0.1:8891/ — Quản lý: http://127.0.0.1:8891/quan-tri/'
