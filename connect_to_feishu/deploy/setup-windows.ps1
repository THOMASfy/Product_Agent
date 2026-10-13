# 在**服务器**（Windows）上安装文件生成依赖（PPT/Word/Excel/PDF）。
# 用户端不需要执行任何命令；他们只用飞书。
#
# 用法（建议以管理员身份运行 PowerShell）：
#   powershell -ExecutionPolicy Bypass -File connect_to_feishu\deploy\setup-windows.ps1
$ErrorActionPreference = "Stop"

Write-Host "==> 安装 Python 3.12"
winget install --id Python.Python.3.12 -e --source winget `
  --accept-package-agreements --accept-source-agreements

Write-Host "==> 安装 LibreOffice"
winget install --id TheDocumentFoundation.LibreOffice -e --source winget `
  --accept-package-agreements --accept-source-agreements

# 让当前会话能看到新装的 python。
$py = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "==> 安装 Python 文件生成库"
& $py -m pip install --upgrade pip
& $py -m pip install python-pptx python-docx openpyxl pdf2image Pillow

Write-Host "==> 校验"
& $py -c "import pptx, docx, openpyxl, PIL; print('python libs OK')"
$soffice = "C:\Program Files\LibreOffice\program\soffice.exe"
if (Test-Path $soffice) { Write-Host "LibreOffice OK: $soffice" }
else { Write-Warning "未找到 soffice，请确认安装。" }

Write-Host "完成。启动连接器时会在日志里打印「文件生成能力」自检结果。"
