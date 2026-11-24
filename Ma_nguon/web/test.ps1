$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
& '.\.venv\Scripts\python.exe' manage.py test store.tests --noinput --verbosity 2
if($LASTEXITCODE -ne 0){throw 'Có kiểm thử chưa đạt. Xem .runtime/evidence/tests_current.json hoặc tên tệp đã chọn qua TEST_EVIDENCE_FILE.'}
& '.\.venv\Scripts\python.exe' manage.py check_stock
