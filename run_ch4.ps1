# run_ch4.ps1 — รันชุดทดสอบสำหรับบทที่ 4 ด้วยค่าตั้งที่ล็อกไว้ (บอท หรือ agent) · 4 พ.ย. 2026
#
# ใช้กับชุดทดสอบไหนก็ได้ (ชุด blind ใหม่ · ชุดตรวจ Modutech เล็ก) — ไม่แก้ชุดทดสอบ ไม่แก้โค้ด
# รันทีละระบบ · ปิด backend ทุกตัวก่อน · ห้ามรันบอทกับ agent พร้อมกัน
#
# ตัวอย่าง (จากโฟลเดอร์ beltbot_plugin_2)
#   บอท:   powershell -ExecutionPolicy Bypass -File .\run_ch4.ps1 -System bot   -Python $BOTPY -Testcases ..\blind_v2.csv -Tag blind2 -ImgDir "<โฟลเดอร์รูป>"
#   agent: powershell -ExecutionPolicy Bypass -File .\run_ch4.ps1 -System agent -Python $PY    -Testcases ..\blind_v2.csv -Tag blind2 -ImgDir "<โฟลเดอร์รูป>"
#   ล็อก commit: เติม -Commit <hash> ทุกคำสั่ง (HEAD ไม่ตรง = หยุด)
#   ชุดเล็ก: ... -System agent -Testcases testcases_modutech_136.csv -Tag modsmall -Rounds 1 -Only "TP-002,TP-011"
#
# ผล:  ..\ch4_<Tag>_<System>_r<รอบ>.json  · บอทมี ..\ch4_<Tag>_bot_r<รอบ>_img.log (การตัดสินเรื่องรูป)
#      ..\ch4_<Tag>_manifest.json  (SHA-256 ของชุดทดสอบ · commit · ค่าตั้งของแต่ละระบบ) — ชุดทดสอบเปลี่ยน = หยุด

param(
    [Parameter(Mandatory = $true)][ValidateSet("bot", "agent")][string]$System,
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$Testcases,
    [Parameter(Mandatory = $true)][string]$Tag,
    [string]$ImgDir = "",
    [int[]]$Rounds = @(1, 2),
    [string]$Only = "",
    [string]$Commit = ""          # ใส่ hash ที่ล็อกไว้ = หยุดถ้า HEAD ไม่ตรง (ไม่ใส่ = ไม่ตรวจข้อนี้)
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"   # ก่อนเทสต์ออฟไลน์ด้วย — ส่งผลผ่าน pipe แล้ว Windows ใช้ cp874 พิมพ์ ✓ ไม่ได้
function Fail($msg) { Write-Host "❌ $msg" -ForegroundColor Red; exit 1 }

Write-Host "== ตรวจก่อนรัน ($System) ==" -ForegroundColor Cyan
& $Python -c "import sys; print(sys.executable)"
if ($LASTEXITCODE -ne 0) { Fail "เรียก python ไม่ได้: $Python" }
if (-not (Test-Path $Testcases)) { Fail "ไม่พบชุดทดสอบ $Testcases" }
if ($ImgDir -and -not (Test-Path $ImgDir)) { Fail "ไม่พบโฟลเดอร์รูป $ImgDir" }

$branch = (git branch --show-current).Trim()
if ($branch -ne "eval-movex-old") { Fail "ต้องอยู่ branch eval-movex-old (ตอนนี้ $branch)" }
if (git status --porcelain -- core brands agent_baseline agent_assistant.py assistant.py run_answer_eval.py) {
    Fail "มีโค้ดแก้ค้างที่ยังไม่ commit — ผลจะอ้างไม่ได้" }
$log = (git log -40 --format=%B) -join "`n"
$need = @{ bot = @("MOVEX_ID_SCRUB", "MOVEX_SERIES_ANSWER", "MOVEX_UNKNOWN_CODE", "BOT_DOMAIN_PRODUCT");
           agent = @("AGENT_DATASHEET_FILES", "AGENT_REPLY_GUARD", "AGENT_RESOLVE_TAB") }
foreach ($w in $need[$System]) { if ($log -notmatch $w) { Fail "ยังไม่มี commit ของสวิตช์ $w — ใส่ patch ก่อน" } }
$commit = (git rev-parse --short HEAD).Trim()
if ($Commit -and -not ((git rev-parse HEAD).Trim().StartsWith($Commit))) { Fail "HEAD ($commit) ไม่ตรงกับ commit ที่ล็อกไว้ ($Commit)" }

# ── ล็อกชุดทดสอบ ──
$sha = (Get-FileHash -Algorithm SHA256 $Testcases).Hash.ToLower()
$manifest = "..\ch4_${Tag}_manifest.json"
$m = @{}
if (Test-Path $manifest) {
    $old = Get-Content $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($old.testcases_sha256 -ne $sha) { Fail "ชุดทดสอบเปลี่ยนจากที่บันทึกไว้ ($($old.testcases_sha256.Substring(0,12)) → $($sha.Substring(0,12))) — ผลสองระบบจะเทียบกันไม่ได้" }
    $old.PSObject.Properties | ForEach-Object { $m[$_.Name] = $_.Value }
}
Write-Host "ชุดทดสอบ $Testcases · SHA-256 $($sha.Substring(0,16))… · commit $commit"

Write-Host "`n== เทสต์ออฟไลน์ (ไม่เสียเงิน) ==" -ForegroundColor Cyan
$tests = @{ bot = @("test_bot_movex_fixes.py"); agent = @("test_agent_reply_guard.py", "test_agent_speed.py") }
foreach ($t in $tests[$System]) { & $Python $t | Select-Object -Last 1; if ($LASTEXITCODE -ne 0) { Fail "$t ไม่ผ่าน" } }

# ── ค่าตั้งที่ล็อก ──
Get-Content .env | Where-Object { $_ -and $_ -notmatch '^\s*#' } | ForEach-Object {
    $k, $v = $_ -split '=', 2; [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim()) }
if (-not $env:GEMINI_API_KEY) { Fail "ไม่มี GEMINI_API_KEY (.env)" }
foreach ($k in "BOT_MODULE", "IMAGE_TEST_LOG", "AGENT_IMAGE_MAX_SIDE", "AGENT_IMAGE_TO_LLM", "AGENT_LAZY",
               "FRONT_INTERPRETER", "BOT_DOMAIN_PRODUCT", "MOVEX_UNKNOWN_CODE", "MOVEX_SERIES_ANSWER", "MOVEX_ID_SCRUB",
               "AGENT_PROMPT", "AGENT_DATASHEET_FILES", "AGENT_REPLY_GUARD", "AGENT_RESOLVE_TAB", "IMAGE_INTERPRETER",
               "AGENT_IMAGE_SURFACE") {
    Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
$env:PYTHONIOENCODING = "utf-8"
$env:GEMINI_THINKING = "low"
$env:GEMINI_MODEL = "gemini-3.8-flash"
$cfg = @{ bot = [ordered]@{ FRONT_INTERPRETER = "llm"; BOT_DOMAIN_PRODUCT = "1"; MOVEX_UNKNOWN_CODE = "1";
                            MOVEX_SERIES_ANSWER = "1"; MOVEX_ID_SCRUB = "1" };
          agent = [ordered]@{ AGENT_PROMPT = "r3"; AGENT_DATASHEET_FILES = "1"; AGENT_REPLY_GUARD = "1"; AGENT_RESOLVE_TAB = "1" } }
foreach ($kv in $cfg[$System].GetEnumerator()) { [Environment]::SetEnvironmentVariable($kv.Key, $kv.Value) }
$module = @{ bot = "assistant"; agent = "agent_assistant" }[$System]

$m["testcases"] = (Resolve-Path $Testcases).Path
$m["testcases_sha256"] = $sha
$m["${System}_commit"] = $commit
$m["${System}_env"] = $cfg[$System]
$m["${System}_python"] = $Python
$m["gemini_thinking"] = "low"
$m["gemini_model"] = "gemini-3.8-flash"
$m["${System}_started"] = (Get-Date -Format s)
($m | ConvertTo-Json -Depth 4) | Out-File -Encoding utf8 $manifest

$t0 = Get-Date
foreach ($r in $Rounds) {
    $out = "..\ch4_${Tag}_${System}_r$r.json"
    if (Test-Path $out) { Fail "$out มีอยู่แล้ว — ไม่เขียนทับไฟล์ผลดิบ" }
    if ($System -eq "bot") { $env:IMAGE_TEST_LOG = (Join-Path (Resolve-Path ..) "ch4_${Tag}_bot_r${r}_img.log") }
    Write-Host "`n== $System · รอบ $r → $out ==" -ForegroundColor Cyan
    $cmdArgs = @("run_answer_eval.py", "--module", $module, "--testcases", $Testcases, "-o", $out)
    if ($ImgDir) { $cmdArgs += @("--img-dir", $ImgDir) }
    if ($Only) { $cmdArgs += @("--only", $Only) }
    & $Python @cmdArgs
    if ($LASTEXITCODE -ne 0) { Fail "รอบ $r ล้ม — ดู error ด้านบน (ไฟล์ผลรอบก่อนหน้ายังอยู่)" }
}
$mins = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
$m["${System}_finished"] = (Get-Date -Format s)
($m | ConvertTo-Json -Depth 4) | Out-File -Encoding utf8 $manifest
Write-Host "`n✅ $System เสร็จใน $mins นาที · ส่งไฟล์ ..\ch4_${Tag}_* มาได้เลย" -ForegroundColor Green
