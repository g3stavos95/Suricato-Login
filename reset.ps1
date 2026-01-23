# ======================================================================================
# reset.ps1 — Documentação (v1.1)
# Autor: Gustavo Pires
# Data: 2026-01-23
# ======================================================================================
# Suricato AutoLogin (F12) - RESET (Windows 10/11)
# Versão: 1.1
# ======================================================================================
# Objetivo:
#   Remover rastros do setup/app no Windows para permitir testes "do zero".
#   - Remove pasta %LOCALAPPDATA%\SuricatoAutoLogin (work/dist/logs/ico)
#   - Remove atalhos .lnk do Desktop e do Menu Iniciar
#   - (Opcional) Desinstala dependências pip --user usadas pelo projeto
#
# Segurança / Robustez:
#   - Só apaga caminhos conhecidos do app (guardrails)
#   - Suporta -WhatIf nativo do PowerShell (via SupportsShouldProcess)
#   - Confirmações explícitas quando ações forem destrutivas
#
# Uso:
#   # Reset padrão (recomendado)
#   powershell -ExecutionPolicy Bypass -File .\reset.ps1
#
#   # Reset incluindo uninstall das dependências pip (mais realista)
#   powershell -ExecutionPolicy Bypass -File .\reset.ps1 -PurgePipUserPackages
#
#   # Sem perguntas (cuidado)
#   powershell -ExecutionPolicy Bypass -File .\reset.ps1 -Yes -PurgePipUserPackages
# ======================================================================================

# CmdletBinding + SupportsShouldProcess habilita -WhatIf/-Confirm para segurança.
[CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact='High')]
param(
  [switch]$Yes,
  [switch]$PurgePipUserPackages
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# -------------------------------
# Configuração do App / Pastas
# -------------------------------
$APP_NAME = "Suricato AutoLogin (F12)"
$APP_SLUG = "SuricatoAutoLogin"

$ROOT_DIR = Join-Path $env:LOCALAPPDATA $APP_SLUG
$DESKTOP_DIR  = [Environment]::GetFolderPath("Desktop")
$STARTMENU_DIR = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$SHORTCUT_DESKTOP = Join-Path $DESKTOP_DIR "$APP_NAME.lnk"
$SHORTCUT_START   = Join-Path $STARTMENU_DIR "$APP_NAME.lnk"

# Dependências pip instaladas via autologin_setup.ps1
$PIP_PKGS = @("pyautogui","pynput","cryptography","pystray","pillow","pyinstaller")

# -------------------------------
# Logging
# -------------------------------
function Write-Info([string]$Msg) { Write-Host "[INFO] $Msg" }
function Write-Warn([string]$Msg) { Write-Warning $Msg }
function Write-Err ([string]$Msg) { Write-Error $Msg }

function Ask-YesNo([string]$Msg) {
  if ($Yes) { return $true }
  try {
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    $res = [System.Windows.Forms.MessageBox]::Show($Msg, "Reset - Suricato AutoLogin", "YesNo", "Question")
    return ($res -eq [System.Windows.Forms.DialogResult]::Yes)
  } catch {
    $ans = Read-Host "$Msg (S/N)"
    return ($ans -match '^[sS]$')
  }
}

# -------------------------------
# Guardrails
# -------------------------------
# Guardrail crítico: impede deletar qualquer coisa fora do escopo do app.
function Assert-SafePath([string]$PathToDelete) {
  if ([string]::IsNullOrWhiteSpace($PathToDelete)) {
    throw "Path vazio/nulo recusado."
  }

  $full = [System.IO.Path]::GetFullPath($PathToDelete)

  # Permitimos deletar somente dentro de:
  #   %LOCALAPPDATA%\SuricatoAutoLogin
  # e atalhos específicos conhecidos
  $allowedRoot = [System.IO.Path]::GetFullPath($ROOT_DIR)

  $isAllowed =
    ($full.StartsWith($allowedRoot, [System.StringComparison]::OrdinalIgnoreCase)) -or
    ($full -ieq ([System.IO.Path]::GetFullPath($SHORTCUT_DESKTOP))) -or
    ($full -ieq ([System.IO.Path]::GetFullPath($SHORTCUT_START)))

  if (-not $isAllowed) {
    throw "Guardrail: recusei apagar caminho fora do escopo do app: $full"
  }
}

function Remove-PathSafe([string]$PathToRemove) {
  if (-not (Test-Path -LiteralPath $PathToRemove)) {
    return
  }
  Assert-SafePath $PathToRemove
  if ($PSCmdlet.ShouldProcess($PathToRemove, "Remove")) {
    Remove-Item -LiteralPath $PathToRemove -Recurse -Force -ErrorAction Stop
    Write-Info "Removido: $PathToRemove"
  }
}

# -------------------------------
# Descobrir um python funcional (best-effort)
# -------------------------------
# Descoberta de Python: tenta 'python' no PATH e depois 'py -3' para resolver sys.executable.
function Get-RealPythonExe {
  # 1) python no PATH
  try {
    $cmd = Get-Command python -ErrorAction Stop
    $py = $cmd.Source
    & $py -c "import sys; print(sys.executable)" > $null 2>&1
    if ($LASTEXITCODE -eq 0) { return $py }
  } catch {}

  # 2) py launcher -> python real
  try {
    $cmd = Get-Command py -ErrorAction Stop
    $pyLauncher = $cmd.Source

    # tenta python 3
    $out = & $pyLauncher -3 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $out) {
      $exe = ($out | Select-Object -First 1).Trim()
      if (Test-Path -LiteralPath $exe) { return $exe }
    }
  } catch {}

  return $null
}

# Opcional: remove pacotes pip --user usados pelo projeto (best-effort).
function Purge-PipUserPackages([string]$PythonExe) {
  if (-not $PythonExe) {
    Write-Warn "Python não encontrado. Pulando desinstalação de dependências pip."
    return
  }

  $msg = "Isso vai tentar desinstalar (pip --user) as dependências do Suricato AutoLogin:`n`n" +
         ($PIP_PKGS -join ", ") + "`n`nDeseja continuar?"
  if (-not (Ask-YesNo $msg)) {
    Write-Info "Pip purge cancelado."
    return
  }

  # pip pode emitir warnings em stderr; falhar só por ExitCode
  Write-Info "Usando Python: $PythonExe"
  $args = @("-m","pip","uninstall","-y") + $PIP_PKGS

  $oldEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $out = & $PythonExe @args 2>&1
    $exit = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $oldEAP
  }

  if ($out) { ($out | Out-String).TrimEnd() | Write-Host }
  if ($exit -ne 0) {
    Write-Warn "pip uninstall retornou exitcode $exit. Se algo ficou instalado, rode manualmente: python -m pip uninstall -y $($PIP_PKGS -join ' ')"
  } else {
    Write-Info "Dependências pip removidas (best-effort)."
  }
}

# ======================================================================================
# Execução
# ======================================================================================
Write-Info "Reset do $APP_NAME (Windows)"
Write-Info "Root dir alvo: $ROOT_DIR"

# 1) Atalhos
if (Test-Path -LiteralPath $SHORTCUT_DESKTOP) {
  if ($Yes -or (Ask-YesNo "Remover atalho do Desktop?`n$SHORTCUT_DESKTOP")) {
    Remove-PathSafe $SHORTCUT_DESKTOP
  } else {
    Write-Info "Atalho do Desktop mantido."
  }
}
if (Test-Path -LiteralPath $SHORTCUT_START) {
  if ($Yes -or (Ask-YesNo "Remover atalho do Menu Iniciar?`n$SHORTCUT_START")) {
    Remove-PathSafe $SHORTCUT_START
  } else {
    Write-Info "Atalho do Menu Iniciar mantido."
  }
}

# 2) Pasta do app (LocalAppData)
if (Test-Path -LiteralPath $ROOT_DIR) {
  if ($Yes -or (Ask-YesNo "Remover completamente a pasta do app (inclui work/dist/logs/ico)?`n$ROOT_DIR")) {
    Remove-PathSafe $ROOT_DIR
  } else {
    Write-Info "Pasta do app mantida."
  }
} else {
  Write-Info "Pasta do app não existe (ok)."
}

# 3) Dependências pip (opcional)
if ($PurgePipUserPackages) {
  $py = Get-RealPythonExe
  Purge-PipUserPackages -PythonExe $py
}

Write-Info "Reset concluído."