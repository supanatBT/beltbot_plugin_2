# run_agent_app.ps1 — เปิดหน้าเว็บเดิม (web/) แต่ backend เป็น agent (agent_assistant) · 6 พ.ย.
#
# ทำไมไม่ใช้ run_app.ps1: สคริปต์นั้นตรวจ venv ของบอท (gradio · google-genai 2.8 · pydantic < 2.12)
# ซึ่ง venv ของ agent ตั้งใจลงคนละรุ่น (requirements_agent.txt: ADK ต้องใช้ google-genai 2.3x) จึงไม่ผ่านเสมอ
# backend (app.py · webapi/) เรียก chat_interaction ของ BOT_MODULE ตัวไหนก็ได้ — agent ใช้สัญญาเดียวกับบอท
#
# ตัวอย่าง
# ค่าตั้งเท่ากับ agent ในชุด blind v2 (run_ch4.ps1 -System agent) + เครื่องมือผิวจากรูป
#   GEMINI_MODEL=gemini-3.8-flash · GEMINI_THINKING=low · AGENT_PROMPT=r3
#   AGENT_DATASHEET_FILES=1 · AGENT_REPLY_GUARD=1 · AGENT_RESOLVE_TAB=1 · AGENT_IMAGE_SURFACE=1
#   ค่าเหล่านี้ทับ .env เสมอ — ตัวที่ขึ้นเว็บจึงเป็นตัวเดียวกับที่ทดสอบ
#
#   .\run_agent_app.ps1                                     # venv ที่ .\.venv-agent · เปิดเครื่องมือผิวจากรูป
#   .\run_agent_app.ps1 -Python "D:\venvs\agent\Scripts\python.exe" -NoImageSurface
param(
    [string]$Python = ".\.venv-agent\Scripts\python.exe",
    [string]$Prompt = "r3",
    [switch]$NoImageSurface
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not [IO.Path]::IsPathRooted($Python)) { $Python = Join-Path $root $Python }

Write-Host "== interpreter ที่จะใช้ (venv ของ agent) ==" -ForegroundColor Cyan
& $Python -c "import sys, google.adk, mcp, fastapi, uvicorn; print(sys.executable); print('google-adk', google.adk.__version__)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "python ตัวนี้ไม่มี google-adk / mcp / fastapi / uvicorn: $Python" -ForegroundColor Red
    Write-Host "ติดตั้ง: & '$Python' -m pip install -r requirements_agent.txt fastapi==0.141.1 starlette==0.52.1 uvicorn==0.52.4 python-multipart==0.0.32"
    exit 1
}
if (-not (Test-Path "$root\.env")) { Write-Host "ไม่มี .env ที่รากโฟลเดอร์" -ForegroundColor Red; exit 1 }

$surface = if ($NoImageSurface) { "0" } else { "1" }
Write-Host "`n== ค่าตั้ง ==" -ForegroundColor Cyan
$cfg = [ordered]@{ BOT_MODULE = "agent_assistant"; GEMINI_MODEL = "gemini-3.8-flash"; GEMINI_THINKING = "low"
                  AGENT_PROMPT = $Prompt; AGENT_DATASHEET_FILES = "1"; AGENT_REPLY_GUARD = "1"; AGENT_RESOLVE_TAB = "1"
                  AGENT_IMAGE_SURFACE = $surface; PYTHONIOENCODING = "utf-8" }
foreach ($kv in $cfg.GetEnumerator()) { Write-Host "   $($kv.Key)=$($kv.Value)" }
Write-Host "   (ค่าอื่นอ่านจาก .env · ค่าข้างบนทับ .env · เท่ากับ agent ชุด blind v2 + ผิวจากรูป)"
Write-Host "   commit $((git -C $root rev-parse --short HEAD).Trim())"
$setenv = ($cfg.GetEnumerator() | ForEach-Object { "`$env:$($_.Key)='$($_.Value)'; " }) -join ""

# ── backend ──────────────────────────────────────────────────
Write-Host "`n== เปิด backend ของ agent (พอร์ต 7860) ==" -ForegroundColor Cyan
$cmd = "cd '$root'; " +
       "Get-Content .env | Where-Object { `$_ -and `$_ -notmatch '^\s*#' } | ForEach-Object { " +
       "`$k,`$v = `$_ -split '=',2; [Environment]::SetEnvironmentVariable(`$k.Trim(), `$v.Trim()) }; " +
       $setenv +
       "& '$Python' -m uvicorn app:app --host 127.0.0.1 --port 7860"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd

Write-Host "รอ backend พร้อม (โหลด Jina + SigLIP + ViT บน CPU ราว 1-2 นาที)..." -NoNewline
$ready = $false
foreach ($i in 1..180) {
    Start-Sleep -Seconds 1
    try {
        $c = New-Object Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", 7860)
        $c.Close(); $ready = $true; break
    } catch { Write-Host "." -NoNewline }
}
if (-not $ready) {
    Write-Host "`n❌ backend ไม่ขึ้นภายใน 3 นาที — ดู error ในหน้าต่างที่เปิดไว้" -ForegroundColor Red
    exit 1
}
Write-Host " พร้อมแล้ว" -ForegroundColor Green

# ── หน้าเว็บ (ตัวเดียวกับบอท) ─────────────────────────────────
Write-Host "`n== เปิดหน้าเว็บ (พอร์ต 3000) ==" -ForegroundColor Cyan
if (-not (Test-Path "$root\web\node_modules")) {
    Write-Host "ยังไม่ได้ npm install — กำลังติดตั้ง (ครั้งแรกใช้เวลาสักครู่)"
    Push-Location "$root\web"; npm install; Pop-Location
}
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\web'; npm run dev"

Start-Sleep -Seconds 4
Write-Host "`nเปิดเบราว์เซอร์ที่ http://localhost:3000 (backend = agent)" -ForegroundColor Green
Start-Process "http://localhost:3000"
