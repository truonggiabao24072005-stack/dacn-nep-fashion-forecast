param(
 [ValidateSet('kiem-tra','cau-truc','bao-cao','sao-luu','thu-phuc-hoi','xuat-luoc-do')]
 [string]$TacVu='kiem-tra'
)
$ErrorActionPreference='Stop'
$databasePython=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if(-not(Test-Path -LiteralPath $databasePython)){throw 'Chưa có môi trường Python. Xem README.md.'}
$env:PYTHONIOENCODING='utf-8'
Push-Location -LiteralPath $PSScriptRoot
try {
 switch($TacVu){
  'sao-luu' {& $databasePython tools/manage_database.py backup}
  'thu-phuc-hoi' {& $databasePython tools/manage_database.py verify}
  'xuat-luoc-do' {& $databasePython tools/manage_database.py export-schema}
  default {& $databasePython tools/manage_database.py query --report $TacVu}
 }
 if($LASTEXITCODE -ne 0){throw 'Tác vụ CSDL chưa hoàn tất. Đọc thông báo lỗi; không coi là kiểm tra đã đạt.'}
}
finally {Pop-Location}
